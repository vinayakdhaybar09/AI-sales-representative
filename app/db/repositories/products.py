"""app/db/repositories/products.py — SQL-only access to the products table.

Layering rule: this module knows SQL and nothing else.
It never imports from services/, api/, or graph/.

All functions accept a psycopg AsyncConnection so the caller controls the
transaction boundary (useful for bulk upserts in the ingestion script).
"""

import json
import logging
from typing import Any

import psycopg
from psycopg.rows import dict_row

logger = logging.getLogger(__name__)


# ─── helpers ──────────────────────────────────────────────────────────────────

def _build_details(product: dict[str, Any]) -> dict[str, Any]:
    """Collect 'extra' product fields into the jsonb details column.

    Anything that doesn't have its own column ends up here: features,
    detailed_information, specifications, images list, discount_percentage,
    and the source snapshot metadata.
    """
    return {
        "features":             product.get("features") or [],
        "detailed_information": product.get("detailed_information") or {},
        "specifications":       product.get("specifications") or {},
        "images":               product.get("images") or [],
        "discount_percentage":  product.get("discount_percentage"),
        "source":               product.get("source") or {},
    }


# ─── write ────────────────────────────────────────────────────────────────────

async def upsert_product(
    conn: psycopg.AsyncConnection,
    product: dict[str, Any],
) -> None:
    """Insert or update a single product row (idempotent, keyed on id).

    Maps JSON shape → columns:
      availability.status  → availability column
      everything else      → direct column or details jsonb
    """
    availability = (
        product.get("availability", {}).get("status", "out_of_stock")
        if isinstance(product.get("availability"), dict)
        else "out_of_stock"
    )

    await conn.execute(
        """
        INSERT INTO products (
            id, category, name, url, image_url, description,
            price, original_price, rating, review_count,
            availability, details
        )
        VALUES (
            %(id)s, %(category)s, %(name)s, %(url)s, %(image_url)s, %(description)s,
            %(price)s, %(original_price)s, %(rating)s, %(review_count)s,
            %(availability)s, %(details)s
        )
        ON CONFLICT (id) DO UPDATE SET
            category         = EXCLUDED.category,
            name             = EXCLUDED.name,
            url              = EXCLUDED.url,
            image_url        = EXCLUDED.image_url,
            description      = EXCLUDED.description,
            price            = EXCLUDED.price,
            original_price   = EXCLUDED.original_price,
            rating           = EXCLUDED.rating,
            review_count     = EXCLUDED.review_count,
            availability     = EXCLUDED.availability,
            details          = EXCLUDED.details
        """,
        {
            "id":               str(product["id"]),
            "category":         product.get("category") or "",
            "name":             product.get("name") or "",
            "url":              product.get("url") or "",
            "image_url":        product.get("image_url") or "",
            "description":      product.get("description") or "",
            "price":            float(product.get("price") or 0),
            "original_price":   float(product.get("original_price") or 0),
            "rating":           float(product.get("rating") or 0),
            "review_count":     int(product.get("review_count") or 0),
            "availability":     availability,
            "details":          json.dumps(_build_details(product)),
        },
    )


# ─── read ─────────────────────────────────────────────────────────────────────

async def get_product_by_id(
    conn: psycopg.AsyncConnection,
    product_id: str,
) -> dict[str, Any] | None:
    """Fetch a single product row by its Shopify id.

    Returns a plain dict (all columns) or None if not found.
    """
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(
            "SELECT * FROM products WHERE id = %s",
            (product_id,),
        )
        return await cur.fetchone()  # type: ignore[return-value]


async def get_products_by_category(
    conn: psycopg.AsyncConnection,
    category: str,
) -> list[dict[str, Any]]:
    """Fetch all products in a given category (case-insensitive exact match).

    Returns a list of plain dicts; empty list if no match.
    """
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(
            "SELECT * FROM products WHERE LOWER(category) = LOWER(%s) ORDER BY name",
            (category,),
        )
        return await cur.fetchall()  # type: ignore[return-value]


async def count_products(conn: psycopg.AsyncConnection) -> int:
    """Return total number of rows in the products table."""
    async with conn.cursor() as cur:
        await cur.execute("SELECT COUNT(*) FROM products")
        row = await cur.fetchone()
        return row[0] if row else 0
