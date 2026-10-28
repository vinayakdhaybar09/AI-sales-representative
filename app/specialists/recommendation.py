"""Recommendation specialist: semantic discovery -> SQL truth -> filters -> rank.

Embeddings only *discover* candidate product IDs. Price, availability, URL and
image always come from the `products` table. Out-of-stock products stay in.
"""

import logging

import psycopg

from app.db.repositories.products import get_products_by_ids
from app.retrieval.search import search
from app.schemas.query import QueryUnderstanding
from app.schemas.specialist import SpecialistOutput
from app.specialists.products import category_matches, normalize_gender, to_record

logger = logging.getLogger(__name__)

CANDIDATES = 20     # vector hits to consider (docs/DECISIONS.md)
RESULTS = 5         # products handed to the Composer
MIN_SCORE = 0.68    # below this a hit is noise (off-topic queries score ~0.6)


def _search_text(query: QueryUnderstanding, search_text: str) -> str:
    """User words plus the extracted terms (richer than either alone)."""
    e, f = query.entities, query.filters
    extra = [e.category or "", *e.use_case, *e.body_area, *e.attributes,
             *f.skin_type, *f.hair_type, *f.required_features]
    return f"{search_text}. {' '.join(x for x in extra if x)}".strip()


async def run(
    conn: psycopg.AsyncConnection, query: QueryUnderstanding, search_text: str
) -> SpecialistOutput:
    warnings: list[str] = []
    hits = await search(conn, _search_text(query, search_text), "product", CANDIDATES)
    hits = [h for h in hits if h.score >= MIN_SCORE]
    if not hits:
        return SpecialistOutput(specialist="recommendation", status="empty",
                                warnings=["no_relevant_products"])

    # Audience: only a customer shopping for women narrows the range (women's and unisex products). "Men" or
    # unknown never removes anything: men's products are the default and women's ones are just ranked later below.
    gender = normalize_gender(query.filters.gender)
    if gender == "women":
        hits = [h for h in hits
                if (h.metadata.get("gender_target") or "unisex") in ("women", "unisex")]

    by_id = {h.source_id: h for h in hits}
    rows = await get_products_by_ids(conn, list(by_id))

    # Hard filters on the single source of truth (products.price).
    f = query.filters
    if f.budget_max is not None or f.budget_min is not None:
        before = len(rows)
        rows = [r for r in rows
                if (f.budget_max is None or float(r["price"]) <= f.budget_max)
                and (f.budget_min is None or float(r["price"]) >= f.budget_min)]
        if before and not rows:
            warnings.append("no_products_within_budget")
    if f.exclusions:
        banned = [x.lower() for x in f.exclusions]
        rows = [r for r in rows if not any(b in r["name"].lower() for b in banned)]

    # Category is a preference, not a wall: names differ across the two files.
    term = query.entities.category
    if term and rows:
        matched = [r for r in rows if category_matches(term, r, by_id[r["id"]].metadata)]
        if matched:
            rows = matched
        else:
            warnings.append("category_not_matched")

    if not rows:
        return SpecialistOutput(specialist="recommendation", status="empty",
                                warnings=warnings or ["no_relevant_products"])

    # Out-of-stock products are demoted, never hidden: in-stock first, similarity order within each group
    # (get_products_by_ids keeps similarity order and sorted() is stable).
    # Men's products are the default audience (about 90% of the range): unless the customer is shopping for
    # women, women's products come after the rest. They are not removed.
    demote_women = gender != "women"
    rows = sorted(rows, key=lambda r: (
        r["availability"] == "out_of_stock",
        demote_women and (by_id[r["id"]].metadata.get("gender_target") or "unisex") == "women",
    ))
    primary = next((r for r in rows if r["availability"] != "out_of_stock"), None)
    if primary is None:
        warnings.append("all_out_of_stock")   # nothing can be offered as the pick
    wants_one = query.context.wants_single_pick
    rows = rows[:1] if wants_one else rows[:RESULTS]
    products = [{**to_record(r), "match_score": round(by_id[r["id"]].score, 3)} for r in rows]
    if any(p["availability"] == "out_of_stock" for p in products):
        warnings.append("includes_out_of_stock")
    return SpecialistOutput(
        specialist="recommendation",
        status="success",
        data={"products": products, "primary_pick": primary["name"] if primary else None,
              "single_pick": wants_one},
        sources=[{"type": "product", "id": p["id"], "name": p["name"]} for p in products],
        warnings=warnings,
    )
