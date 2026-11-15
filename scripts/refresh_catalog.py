"""scripts/refresh_catalog.py — refresh the product catalog from the live BSC store.

Usage (project root, venv activated):
    python -m scripts.refresh_catalog --dry-run      # fetch + diff only, write nothing
    python -m scripts.refresh_catalog                # upsert products, embed new/changed ones
    python -m scripts.refresh_catalog --no-embed     # skip embeddings
    python -m scripts.refresh_catalog --feed file.json   # use a saved feed (offline / tests)

Why this exists
---------------
The catalog must be refreshable, not hard-coded. The store exposes a public
Shopify feed (/products.json) with title, variants, price, compare-at price,
stock, images and tags. Each run:

1. Fetches every page of the feed (polite: backoff on 429/5xx).
2. Normalizes each product to the shape `products` expects.
3. Keeps rich fields the feed does not carry (rating, review_count, features,
   how-to, FAQs) from the row already in the DB, so a refresh never erases them.
4. Diffs against the DB: new / delisted / price changes / stock changes, and
   writes the report to data/refresh_reports/<timestamp>.json (shown in admin).
5. Upserts changed rows. Products that vanished from the feed are NOT deleted:
   they are marked out_of_stock with details.delisted = true.
6. Embeds only products that are new or whose searchable text changed.

Feed-only fields (price, stock, url, image) overwrite the DB every run, since
the store is the source of truth for them.
"""

import argparse
import asyncio
import hashlib
import html
import json
import logging
import pathlib
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from typing import Any

import psycopg
from pgvector.psycopg import register_vector_async
from psycopg.rows import dict_row

from app.core.config import get_settings
from app.core.logging import setup_logging
from app.db.repositories.products import upsert_product

setup_logging()
logger = logging.getLogger(__name__)

STORE = "https://www.bombayshavingcompany.com"
REPORT_DIR = pathlib.Path("data/refresh_reports")
USER_AGENT = "BSC-Assistant-CatalogRefresh/1.0 (demo; contact: site owner)"

# The store's product_type values are inconsistent; map them to the canonical
# categories already used by the products table.
CATEGORY_MAP = {
    "trimmer": "Trimmers", "trimmers": "Trimmers",
    "skin care": "Skin Care", "skin": "Skin Care", "skin++": "Skin Care", "face care": "Skin Care",
    "razors & blades": "Razors & Blades", "face razor": "Razors & Blades",
    "disposable razor": "Razors & Blades",
    "body razor & blades": "Body Razor & Blades",
    "shave consumables": "Shave Consumables", "shave": "Shave Consumables",
    "beard care": "Beard Care", "beard": "Beard Care",
    "fragrance": "Fragrance", "perfume": "Fragrance",
    "hrc+": "Hair Removal", "hair removal": "Hair Removal",
    "accessories": "Accessories", "bath": "Bath",
}


# ─── fetch ───────────────────────────────────────────────────────────────────

def fetch_feed(max_pages: int = 10) -> list[dict[str, Any]]:
    """Download all pages of /products.json (250 per page) with retry/backoff."""
    products: list[dict[str, Any]] = []
    for page in range(1, max_pages + 1):
        url = f"{STORE}/products.json?limit=250&page={page}"
        batch = None
        for attempt in range(1, 5):
            try:
                req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
                with urllib.request.urlopen(req, timeout=30) as resp:
                    batch = json.load(resp).get("products", [])
                break
            except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
                wait = 3 * 2 ** (attempt - 1)
                logger.warning("feed page %d attempt %d failed (%s); retrying in %ds", page, attempt, exc, wait)
                time.sleep(wait)
        if batch is None:
            raise RuntimeError(f"Could not fetch {url}")
        if not batch:
            break
        products.extend(batch)
        time.sleep(1.0)  # politeness gap
    logger.info("Fetched %d products from the live feed", len(products))
    return products


# ─── normalize ───────────────────────────────────────────────────────────────

def _strip_html(raw: str) -> str:
    text = re.sub(r"<!--.*?-->|<style.*?</style>|<script.*?</script>", " ", raw or "", flags=re.S)
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", html.unescape(text)).strip()


def normalize(item: dict[str, Any]) -> dict[str, Any]:
    """Shopify feed item → dict with the columns of the `products` table."""
    variants = item.get("variants") or []
    in_stock_variants = [v for v in variants if v.get("available")]
    priced = in_stock_variants or variants
    prices = [float(v["price"]) for v in priced if v.get("price") not in (None, "")]
    price = min(prices) if prices else 0.0
    compare = [float(v["compare_at_price"]) for v in priced if v.get("compare_at_price")]
    original = max(compare + [price]) if prices else 0.0
    images = [i["src"] for i in item.get("images") or [] if i.get("src")]
    ptype = (item.get("product_type") or "").strip()
    return {
        "id": str(item["id"]),
        "category": CATEGORY_MAP.get(ptype.lower(), ptype or "Other"),
        "name": (item.get("title") or "").strip(),
        "url": f"{STORE}/products/{item['handle']}",
        "image_url": images[0] if images else "",
        "images": images,
        "description": _strip_html(item.get("body_html", "")),
        "price": price,
        "original_price": original,
        "discount_percentage": round((original - price) / original * 100) if original > price > 0 else None,
        "availability": {"status": "in_stock" if in_stock_variants else "out_of_stock"},
        "tags": item.get("tags") or [],
        "variants": [
            {"id": str(v["id"]), "title": v.get("title"), "price": float(v["price"]),
             "available": bool(v.get("available")), "sku": v.get("sku")}
            for v in variants if v.get("price") not in (None, "")
        ],
        "source": {
            "url": f"{STORE}/products/{item['handle']}",
            "source_type": "shopify_feed",
            "scraped_at": datetime.now(timezone.utc).isoformat(),
        },
    }


def embed_text(p: dict[str, Any]) -> str:
    """Text embedded for discovery. Same recipe for every product, so refreshes are comparable."""
    parts = [p["name"], p["category"], " ".join(p.get("tags") or []), p.get("description", "")[:1200]]
    return "\n".join(x for x in parts if x)


def text_hash(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:16]


# ─── merge + diff ────────────────────────────────────────────────────────────

def merge_with_existing(new: dict[str, Any], old: dict[str, Any] | None) -> dict[str, Any]:
    """Keep rich fields the feed lacks (rating, features, how-to, FAQs) from the stored row."""
    merged = dict(new)
    if not old:
        return merged
    details = old.get("details") or {}
    merged["rating"] = float(old.get("rating") or 0)
    merged["review_count"] = int(old.get("review_count") or 0)
    merged["features"] = details.get("features") or []
    merged["detailed_information"] = details.get("detailed_information") or {}
    old_spec = details.get("specifications") or {}
    merged["specifications"] = {**old_spec, "variants": new["variants"], "tags": new["tags"]}
    # A long scraped description is better than a short feed one; keep it if the feed one is empty.
    if not merged["description"]:
        merged["description"] = old.get("description") or ""
    return merged


def build_report(feed: list[dict], stored: dict[str, dict]) -> dict[str, Any]:
    live_ids = {p["id"] for p in feed}
    report: dict[str, Any] = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "feed_count": len(feed), "stored_count": len(stored),
        "new": [], "delisted": [], "price_changes": [], "stock_changes": [],
    }
    for p in feed:
        old = stored.get(p["id"])
        if old is None:
            report["new"].append({"id": p["id"], "name": p["name"], "price": p["price"]})
            continue
        if abs(float(old["price"]) - p["price"]) > 0.5:
            report["price_changes"].append(
                {"id": p["id"], "name": p["name"], "old": float(old["price"]), "new": p["price"]})
        new_stock = p["availability"]["status"]
        if old["availability"] != new_stock:
            report["stock_changes"].append(
                {"id": p["id"], "name": p["name"], "old": old["availability"], "new": new_stock})
    for pid, old in stored.items():
        if pid not in live_ids and not (old.get("details") or {}).get("delisted"):
            report["delisted"].append({"id": pid, "name": old["name"]})
    return report


# ─── DB + embeddings ─────────────────────────────────────────────────────────

async def load_stored(conn: psycopg.AsyncConnection) -> dict[str, dict]:
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute("SELECT * FROM products")
        return {r["id"]: r for r in await cur.fetchall()}


async def embed_changed(conn: psycopg.AsyncConnection, feed: list[dict]) -> int:
    """Embed products that are new or whose embed text hash changed. Returns count embedded."""
    from app.db.repositories.embeddings import upsert_embedding
    from scripts.ingest_embeddings import embed_batch, BATCH_SIZE, PAUSE_SECONDS

    cur = await conn.execute("SELECT source_id, metadata FROM embeddings WHERE source_type='product'")
    known = {r[0]: (r[1] or {}) for r in await cur.fetchall()}
    todo = []
    for p in feed:
        text = embed_text(p)
        old_meta = known.get(p["id"])
        # Rows embedded by the old enrichment pipeline carry richer metadata and
        # no hash: leave them alone unless the product is brand new.
        if old_meta is None or (old_meta.get("text_hash") and old_meta["text_hash"] != text_hash(text)):
            todo.append((p, text))
    logger.info("%d products need embedding", len(todo))
    done = 0
    for i in range(0, len(todo), BATCH_SIZE):
        chunk = todo[i:i + BATCH_SIZE]
        vectors = await embed_batch([t for _, t in chunk])
        for (p, text), vec in zip(chunk, vectors, strict=True):
            meta = {"category": p["category"], "tags": p["tags"], "text_hash": text_hash(text),
                    "derived": "feed"}
            await upsert_embedding(conn, "product", p["id"], text, meta, vec)
            done += 1
        await asyncio.sleep(PAUSE_SECONDS)
    return done


async def run(dry_run: bool, embed: bool, feed_file: str | None) -> int:
    settings = get_settings()
    if not settings.database_url:
        logger.error("DATABASE_URL is not set.")
        return 1
    raw = json.load(open(feed_file))["products"] if feed_file else fetch_feed()
    feed = [normalize(i) for i in raw]

    conninfo = settings.database_url.get_secret_value()
    async with await psycopg.AsyncConnection.connect(conninfo, autocommit=True) as conn:
        await register_vector_async(conn)  # needed to write embedding vectors
        stored = await load_stored(conn)
        report = build_report(feed, stored)
        for key in ("new", "delisted", "price_changes", "stock_changes"):
            logger.info("%s: %d", key, len(report[key]))
        if dry_run:
            print(json.dumps({k: (v[:8] if isinstance(v, list) else v) for k, v in report.items()}, indent=1))
            return 0

        for p in feed:
            await upsert_product(conn, merge_with_existing(p, stored.get(p["id"])))
        live_ids = {p["id"] for p in feed}
        for pid, old in stored.items():
            if pid not in live_ids:
                details = dict(old.get("details") or {}, delisted=True)
                await conn.execute(
                    "UPDATE products SET availability='out_of_stock', details=%s::jsonb WHERE id=%s",
                    (json.dumps(details), pid))
        report["embedded"] = await embed_changed(conn, feed) if embed else 0

    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    out = REPORT_DIR / f"{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}.json"
    out.write_text(json.dumps(report, indent=1))
    logger.info("Refresh complete. Report: %s", out)
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--no-embed", action="store_true")
    ap.add_argument("--feed", help="path to a saved products.json instead of fetching")
    a = ap.parse_args()
    sys.exit(asyncio.run(run(a.dry_run, not a.no_embed, a.feed)))
