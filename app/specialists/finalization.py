"""Product finalization specialist: narrow the options down to the best 1-3.

The pick is made here, in plain Python, never by the LLM: the Composer only
explains it. Candidates come from the products already shown in this
conversation (the "pool"); if there is no pool, or the customer's criteria rule
out all of it, we run the recommendation search and pick from that instead.
Price and availability always come from the `products` table.
"""

import logging
from typing import Any

import psycopg

from app.db.repositories.products import get_products_by_ids
from app.response.text import clean_text
from app.schemas.query import QueryUnderstanding
from app.schemas.specialist import SpecialistOutput
from app.specialists import recommendation
from app.specialists.products import _tokens, to_record

logger = logging.getLogger(__name__)

MAX_RESULTS = 3
REVIEW_WEIGHT = 20          # reviews needed before a product's own rating outweighs the average
DEFAULT_PRIOR = 4.0         # assumed average rating when nothing in the pool has reviews
DEFAULT_MATCH = 0.7         # similarity assumed when the pool has no saved score for a product
MATCH_FLOOR = 0.6           # cosine scores below this carry no signal (see recommendation.MIN_SCORE)
RATING_FLOOR = 3.0          # catalogue ratings sit in 4-5; stretch 3..5 to 0..1 so small gaps still count


def requested_count(query: QueryUnderstanding) -> int:
    """How many products the customer wants: 1 unless they said otherwise, never above 3."""
    n = query.filters.result_limit
    return max(1, min(MAX_RESULTS, n)) if n else 1


def _has_reviews(row: dict[str, Any]) -> bool:
    return int(row.get("review_count") or 0) > 0 and float(row.get("rating") or 0) > 0


def weighted_rating(row: dict[str, Any], prior: float) -> float:
    """Rating pulled toward the pool average when there are few reviews.

    Without this a product with one 5-star review would beat one with 200
    reviews averaging 4.8.
    """
    if not _has_reviews(row):
        return prior
    votes, rating = int(row["review_count"]), float(row["rating"])
    return (votes / (votes + REVIEW_WEIGHT)) * rating + (REVIEW_WEIGHT / (votes + REVIEW_WEIGHT)) * prior


def _product_tokens(row: dict[str, Any]) -> set[str]:
    details = row.get("details") or {}
    info = details.get("detailed_information") or {}
    benefits = info.get("benefits") if isinstance(info, dict) else []
    parts = [row.get("name"), row.get("category"), clean_text(row.get("description"), 1500),
             *(details.get("features") or []), *(benefits or [])]
    return _tokens(" ".join(str(p) for p in parts if p).replace("_", " "))


def _need_terms(query: QueryUnderstanding) -> list[str]:
    e, f = query.entities, query.filters
    return [t.replace("_", " ") for t in [*e.use_case, *e.body_area, *f.skin_type, *f.hair_type, *f.required_features]]


def fit(row: dict[str, Any], terms: list[str]) -> tuple[float, list[str]]:
    """Share of the customer's stated needs that appear in the product text, and which ones."""
    if not terms:
        return 0.0, []
    tokens = _product_tokens(row)
    matched = [t for t in terms if _tokens(t) and _tokens(t) <= tokens]
    return len(matched) / len(terms), matched


def criteria_lines(query: QueryUnderstanding) -> list[str]:
    """The customer's criteria as short readable lines (shown to the Composer)."""
    e, f = query.entities, query.filters
    lines = []
    if e.category:
        lines.append(f"product type: {e.category}")
    if f.budget_min is not None and f.budget_max is not None:
        lines.append(f"budget between ₹{f.budget_min:g} and ₹{f.budget_max:g}")
    elif f.budget_max is not None:
        lines.append(f"budget up to ₹{f.budget_max:g}")
    elif f.budget_min is not None:
        lines.append(f"budget from ₹{f.budget_min:g}")
    for label, values in (("use", e.use_case), ("body area", e.body_area), ("skin type", f.skin_type),
                          ("hair type", f.hair_type), ("needs", f.required_features), ("avoid", f.exclusions)):
        if values:
            lines.append(f"{label}: {', '.join(v.replace('_', ' ') for v in values)}")
    if f.priority == "lowest_price":
        lines.append("priority: lowest price")
    elif f.priority == "highest_rated":
        lines.append("priority: highest rated")
    return lines


def _reasons(row: dict[str, Any], position: int, matched: list[str], query: QueryUnderstanding) -> list[str]:
    """Short factual reasons, built only from the product row and the customer's criteria."""
    f = query.filters
    price = float(row["price"])
    reasons = []
    if position == 0 and f.priority == "lowest_price":
        reasons.append("lowest price among the qualifying options")
    if position == 0 and f.priority == "highest_rated":
        reasons.append("best rated among the qualifying options")
    if _has_reviews(row):
        reasons.append(f"rated {float(row['rating']):g}/5 from {int(row['review_count'])} reviews")
    else:
        reasons.append("no customer reviews yet")
    if f.budget_max is not None:
        reasons.append(f"₹{price:g}, within your ₹{f.budget_max:g} budget")
    else:
        reasons.append(f"priced at ₹{price:g}")
    original = float(row.get("original_price") or 0)
    if original > price:
        reasons.append(f"on offer: ₹{price:g} instead of ₹{original:g}")
    if matched:
        reasons.append("fits your need: " + ", ".join(matched))
    reasons.append("in stock" if row["availability"] == "in_stock" else "Currently out of stock")
    return reasons


def select(
    rows: list[dict[str, Any]],
    scores: dict[str, float],
    query: QueryUnderstanding,
    limit: int,
) -> tuple[list[dict[str, Any]], list[str], str]:
    """Pick up to `limit` products. Returns (products, warnings, ranking_basis).

    Pure logic: hard criteria -> in-stock only (out-of-stock only if nothing
    else qualifies) -> rank by the customer's priority, else by quality.
    """
    f = query.filters
    warnings: list[str] = []

    eligible = [r for r in rows
                if (f.budget_max is None or float(r["price"]) <= f.budget_max)
                and (f.budget_min is None or float(r["price"]) >= f.budget_min)]
    banned = [x.lower() for x in f.exclusions]
    eligible = [r for r in eligible if not any(b in r["name"].lower() for b in banned)]

    in_stock = [r for r in eligible if r["availability"] == "in_stock"]
    if in_stock:
        eligible = in_stock
    elif eligible:
        warnings.append("selected_out_of_stock")
    if not eligible:
        return [], warnings, "quality"

    rated = [float(r["rating"]) for r in eligible if _has_reviews(r)]
    prior = sum(rated) / len(rated) if rated else DEFAULT_PRIOR
    terms = _need_terms(query)

    scored = []
    for r in eligible:
        fit_score, matched = fit(r, terms)
        match = scores.get(str(r["id"]), DEFAULT_MATCH)
        match_norm = max(0.0, min(1.0, (match - MATCH_FLOOR) / (1 - MATCH_FLOOR)))
        wr = weighted_rating(r, prior)
        rating_norm = max(0.0, min(1.0, (wr - RATING_FLOOR) / (5 - RATING_FLOOR)))
        quality = 0.55 * rating_norm + 0.25 * fit_score + 0.20 * match_norm
        scored.append((r, quality, wr, matched, match))

    if f.priority == "lowest_price":
        scored.sort(key=lambda t: (float(t[0]["price"]), -t[1]))
        basis = "priority"
    elif f.priority == "highest_rated":
        scored.sort(key=lambda t: (-t[2], -t[1]))
        basis = "priority"
    else:
        scored.sort(key=lambda t: -t[1])
        basis = "quality"

    picked = []
    for position, (row, _quality, _wr, matched, match) in enumerate(scored[:limit]):
        picked.append({
            **to_record(row),
            "match_score": round(match, 3),
            "rank": position + 1,
            "selection_reasons": _reasons(row, position, matched, query),
        })
    if len(picked) < limit and limit > 1:
        warnings.append("fewer_results_than_requested")
    return picked, warnings, basis


def _empty(extra: list[str]) -> SpecialistOutput:
    return SpecialistOutput(
        specialist="product_finalization", status="empty",
        warnings=["no_products_match_criteria", *[w for w in extra if w != "no_relevant_products"]],
    )


async def run(
    conn: psycopg.AsyncConnection,
    query: QueryUnderstanding,
    search_text: str,
    pool_ids: list[str],
    pool_scores: dict[str, float],
) -> SpecialistOutput:
    """`query` already has the customer's saved preferences filled in (see the graph node)."""
    limit = requested_count(query)
    warnings: list[str] = []
    source = "previous_results"
    scores = dict(pool_scores)

    rows = await get_products_by_ids(conn, pool_ids) if pool_ids else []
    picked: list[dict[str, Any]] = []
    basis = "quality"
    if rows:
        picked, warnings, basis = select(rows, scores, query, limit)

    if not picked:
        # No pool, or none of it fits: search the catalogue with the same criteria.
        fresh = await recommendation.run(conn, query, search_text)
        if fresh.status != "success":
            return _empty(fresh.warnings)
        source = "new_search"
        rows = fresh.data["products"]
        scores = {str(p["id"]): p["match_score"] for p in rows}
        picked, warnings, basis = select(rows, scores, query, limit)
        if pool_ids and rows:
            warnings.append("widened_search")
        if not picked:
            return _empty(warnings)

    pool = [{"id": str(r["id"]), "match_score": scores.get(str(r["id"]), DEFAULT_MATCH)} for r in rows]
    logger.info("Finalization picked %d of %d candidates (source=%s, basis=%s)",
                len(picked), len(rows), source, basis)
    return SpecialistOutput(
        specialist="product_finalization",
        status="success",
        data={
            "products": picked,
            "pool": pool,
            "pool_source": source,
            "ranking_basis": basis,
            "criteria_applied": criteria_lines(query),
            "requested": limit,
        },
        sources=[{"type": "product", "id": p["id"], "name": p["name"]} for p in picked],
        warnings=warnings,
    )
