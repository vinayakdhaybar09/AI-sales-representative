"""Comparison specialist: resolve 2+ products by name, return comparable facts.

Direct SQL first; embeddings only to resolve fuzzy names. Product names are not
unique in the data, so an ambiguous name returns every match plus a warning
instead of silently picking one.
"""

import logging

import psycopg

from app.db.repositories.products import find_products_by_name, get_products_by_ids
from app.retrieval.search import search
from app.schemas.query import QueryUnderstanding
from app.schemas.specialist import MAX_COMPARED_PRODUCTS as MAX_PRODUCTS, SpecialistOutput
from app.specialists.products import match_shown_products, to_record

logger = logging.getLogger(__name__)

FUZZY_MIN_SCORE = 0.75
MAX_PER_NAME = 3
COMPARABLE_FIELDS = [
    "price", "original_price", "rating", "review_count", "availability",
    "category", "description", "details.features", "details.detailed_information.benefits", "details.specifications",
]


async def _resolve(conn: psycopg.AsyncConnection, name: str, warnings: list[str]) -> list[dict]:
    rows, how = await find_products_by_name(conn, name, MAX_PER_NAME)
    if not rows:
        hits = await search(conn, name, "product", 1)
        if hits and hits[0].score >= FUZZY_MIN_SCORE:
            rows = await get_products_by_ids(conn, [hits[0].source_id])
            if rows:
                warnings.append(f"fuzzy_match: '{name}' -> '{rows[0]['name']}'")
    elif len(rows) > 1:
        warnings.append(f"ambiguous_product_name: '{name}' matches {len(rows)} products")
    return rows


async def run(
    conn: psycopg.AsyncConnection,
    query: QueryUnderstanding,
    previous_ids: list[str],
    shown_products: list[dict] | None = None,
) -> SpecialistOutput:
    warnings: list[str] = []
    resolved: dict[str, dict] = {}
    unresolved: list[str] = []

    for name in query.entities.products:
        # "the cream" / "the spray" mean products we just showed: try those before searching the catalogue.
        shown = match_shown_products(name, shown_products or [])
        if shown:
            rows = await get_products_by_ids(conn, [p["id"] for p in shown])
            if len(rows) > 1:
                warnings.append(f"ambiguous_product_name: '{name}' matches {len(rows)} products")
        else:
            rows = []
        if not rows:
            rows = await _resolve(conn, name, warnings)
        if not rows:
            unresolved.append(name)
        # One product per name the customer said: several matches ("the spray") are reported, not all compared.
        for row in rows[:1]:
            resolved.setdefault(row["id"], row)

    # Top up from products shown earlier ("compare it with the first one").
    if len(resolved) < 2 and previous_ids:
        for row in await get_products_by_ids(conn, previous_ids):
            resolved.setdefault(row["id"], row)
            if len(resolved) >= 2:
                break

    if len(resolved) > MAX_PRODUCTS:
        warnings.append(f"comparison_capped: compared the first {MAX_PRODUCTS} of {len(resolved)} products")
        resolved = dict(list(resolved.items())[:MAX_PRODUCTS])

    if len(resolved) < 2:
        warnings.append("could_not_resolve_two_products")
        return SpecialistOutput(
            specialist="comparison", status="empty",
            data={"products": [to_record(r) for r in resolved.values()], "unresolved": unresolved},
            warnings=warnings,
        )

    products = [to_record(r) for r in resolved.values()]
    if any(p["availability"] == "out_of_stock" for p in products):
        warnings.append("includes_out_of_stock")
    return SpecialistOutput(
        specialist="comparison",
        status="success",
        data={"products": products, "comparable_fields": COMPARABLE_FIELDS, "unresolved": unresolved},
        sources=[{"type": "product", "id": p["id"], "name": p["name"]} for p in products],
        warnings=warnings,
    )
