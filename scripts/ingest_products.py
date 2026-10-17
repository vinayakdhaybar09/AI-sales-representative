"""scripts/ingest_products.py — load products table from the JSON data file.

Usage (from project root, venv activated):
    python -m scripts.ingest_products

What it does
------------
1. Reads data/bombay-shaving-product-data.json (structure: {"categories": [...]}).
2. Walks every product in every category.
3. Upserts each product into the `products` table (idempotent: safe to re-run).
4. Logs a summary: total products found, inserted/updated, skipped on error.

Data rule (from AGENTS.md): data is used as-is; do not clean or fix it.
Any per-product error is logged and skipped so a single bad row does not
abort the whole run.
"""

import asyncio
import json
import logging
import pathlib
import sys

import psycopg

from app.core.config import get_settings
from app.core.logging import setup_logging
from app.db.repositories.products import upsert_product

setup_logging()
logger = logging.getLogger(__name__)

DATA_FILE = pathlib.Path("data/bombay-shaving-product-data.json")


def load_products(path: pathlib.Path) -> list[dict]:
    """Read and flatten all products from the JSON file.

    The file has a top-level 'categories' array; each category holds
    a 'products' array. We flatten everything into one list.
    """
    with path.open(encoding="utf-8") as f:
        raw = json.load(f)

    products: list[dict] = []
    for cat in raw.get("categories", []):
        for product in cat.get("products", []):
            products.append(product)

    logger.info("Loaded %d products from %s", len(products), path)
    return products


async def run() -> None:
    """Main async entry point."""
    settings = get_settings()

    if not settings.database_url:
        logger.error(
            "DATABASE_URL is not set. "
            "Add it to .env and retry: DATABASE_URL=postgresql://..."
        )
        sys.exit(1)

    conninfo = settings.database_url.get_secret_value()

    products = load_products(DATA_FILE)
    total = len(products)
    ok = 0
    errors = 0

    # Use a single connection (not the pool) because this is a one-off script
    # that runs outside the FastAPI process.
    async with await psycopg.AsyncConnection.connect(conninfo, autocommit=False) as conn:
        for product in products:
            pid = product.get("id", "<unknown>")
            try:
                await upsert_product(conn, product)
                ok += 1
                if ok % 50 == 0:
                    logger.info("Progress: %d / %d upserted", ok, total)
            except Exception as exc:
                logger.error("Failed to upsert product id=%s: %s", pid, exc)
                errors += 1

        # Commit once at the end for efficiency.
        await conn.commit()

    logger.info(
        "Ingestion complete — total=%d  ok=%d  errors=%d",
        total, ok, errors,
    )
    if errors:
        logger.warning(
            "%d products were skipped due to errors (see above).", errors
        )
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(run())
