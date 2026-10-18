"""scripts/ingest_embeddings.py — embed products, blog chunks and support items.

Usage (project root, venv activated):
    python -m scripts.ingest_embeddings                 # all sources, only missing rows
    python -m scripts.ingest_embeddings --only blog     # one source
    python -m scripts.ingest_embeddings --force         # re-embed rows that already exist

What it does
------------
1. Builds the text to embed for each item exactly as docs/DATA.md specifies.
2. Skips items already stored (so a crashed run resumes where it stopped).
3. Embeds in small batches, backing off when Mistral rate-limits us.
4. Checks every vector has `embedding_dimensions` (1024) numbers, then upserts
   on (source_type, source_id) — re-running never creates duplicates.
5. Prints rows per source_type at the end.

Data rule: data is used as-is (no cleaning). Rows that fail are logged and
skipped; the run exits non-zero if anything failed.
"""

import argparse
import asyncio
import json
import logging
import pathlib
import sys
from typing import Any

import psycopg
from pgvector.psycopg import register_vector_async

from app.core.config import get_settings
from app.core.logging import setup_logging
from app.db.repositories.embeddings import (
    count_by_source_type,
    existing_source_ids,
    upsert_embedding,
)
from app.llm.models import MissingApiKeyError, get_embeddings

setup_logging()
logger = logging.getLogger(__name__)

DATA_DIR = pathlib.Path("data")
PRODUCTS_FILE = DATA_DIR / "bombay-shaving-enriched-products-data-for-embeddings.json"
BLOGS_FILE = DATA_DIR / "bsc-blogs-for-embeddings.json"
SUPPORT_FILE = DATA_DIR / "bsc-support-for-embeddings.json"

BATCH_SIZE = 16          # texts per Mistral request
PAUSE_SECONDS = 1.0      # polite gap between batches (free tier is rate limited)
BATCH_ATTEMPTS = 4       # our own retries on top of the client's 429 handling

# An item is (source_id, text_to_embed, metadata)
Item = tuple[str, str, dict[str, Any]]


def _join(*parts: Any) -> str:
    """Join non-empty parts with newlines."""
    return "\n".join(str(p).strip() for p in parts if p and str(p).strip())


def _load(path: pathlib.Path) -> Any:
    with path.open(encoding="utf-8") as f:
        return json.load(f)


# ─── text builders (docs/DATA.md → "What gets embedded") ─────────────────────

def product_items() -> list[Item]:
    items: list[Item] = []
    for p in _load(PRODUCTS_FILE):
        text = _join(
            p.get("product_name"),
            p.get("category"),
            p.get("product_type"),
            p.get("gender_target"),
            p.get("short_benefit_summary"),
            p.get("searchable_text"),
        )
        meta = {
            k: p.get(k)
            for k in ("category", "product_type", "gender_target", "skin_type",
                      "concerns", "tags", "key_ingredients")
        }
        items.append((str(p["product_id"]), text, meta))
    return items


def blog_items() -> list[Item]:
    items: list[Item] = []
    for blog in _load(BLOGS_FILE)["blogs"]:
        for index, chunk in enumerate(blog.get("chunks", [])):
            text = _join(
                blog.get("title"), blog.get("category"),
                chunk.get("heading"), chunk.get("content"),
            )
            meta = {
                "blog_id": blog["id"],
                "title": blog.get("title"),
                "category": blog.get("category"),
                "heading": chunk.get("heading"),
                "url": blog.get("url"),  # metadata only, not embedded
            }
            items.append((f"{blog['id']}:{index}", text, meta))
    return items


def support_items() -> list[Item]:
    data = _load(SUPPORT_FILE)
    items: list[Item] = []
    for index, faq in enumerate(data.get("faqs", [])):
        text = _join(faq.get("question"), faq.get("answer"), faq.get("category"))
        meta = {"kind": "faq", "category": faq.get("category")}
        items.append((f"faq:{index}", text, meta))
    for index, policy in enumerate(data.get("policies", [])):
        text = _join(policy.get("topic"), policy.get("content"))
        meta = {"kind": "policy", "topic": policy.get("topic")}
        items.append((f"policy:{index}", text, meta))
    return items


BUILDERS = {"product": product_items, "blog": blog_items, "support": support_items}


# ─── embedding with backoff ──────────────────────────────────────────────────

async def embed_batch(texts: list[str]) -> list[list[float]]:
    """Embed one batch, retrying with exponential backoff on any API error."""
    embeddings = get_embeddings()
    for attempt in range(1, BATCH_ATTEMPTS + 1):
        try:
            return await embeddings.aembed_documents(texts)
        except Exception as exc:
            if attempt == BATCH_ATTEMPTS:
                raise
            wait = 5 * 2 ** (attempt - 1)
            logger.warning(
                "Embedding batch failed (attempt %d/%d): %s — retrying in %ds",
                attempt, BATCH_ATTEMPTS, exc, wait,
            )
            await asyncio.sleep(wait)
    raise AssertionError("unreachable")


async def ingest_source(
    conn: psycopg.AsyncConnection, source_type: str, force: bool, dims: int
) -> tuple[int, int, int]:
    """Returns (embedded, skipped_existing, failed) for one source type."""
    items = BUILDERS[source_type]()
    done = set() if force else await existing_source_ids(conn, source_type)
    todo = [i for i in items if i[0] not in done]
    skipped = len(items) - len(todo)
    logger.info(
        "%s: %d items, %d already stored, %d to embed",
        source_type, len(items), skipped, len(todo),
    )

    embedded = failed = 0
    for start in range(0, len(todo), BATCH_SIZE):
        batch = todo[start:start + BATCH_SIZE]
        valid = [i for i in batch if i[1].strip()]
        failed += len(batch) - len(valid)  # empty text cannot be embedded
        if not valid:
            continue
        try:
            vectors = await embed_batch([i[1] for i in valid])
        except Exception as exc:
            logger.error("%s: batch at %d failed permanently: %s", source_type, start, exc)
            failed += len(valid)
            continue

        # One short transaction per batch so progress survives a crash. The
        # connection is autocommit: Neon drops connections left idle inside a
        # transaction while we wait on the embedding API.
        async with conn.transaction():
            for (source_id, text, meta), vector in zip(valid, vectors, strict=True):
                if len(vector) != dims:
                    logger.error("%s %s: got %d dims, expected %d — skipped",
                                 source_type, source_id, len(vector), dims)
                    failed += 1
                    continue
                await upsert_embedding(conn, source_type, source_id, text, meta, vector)
                embedded += 1
        logger.info("%s: %d/%d embedded", source_type, embedded, len(todo))
        await asyncio.sleep(PAUSE_SECONDS)

    return embedded, skipped, failed


async def run(only: str | None, force: bool) -> int:
    settings = get_settings()
    if not settings.database_url:
        logger.error("DATABASE_URL is not set. Add it to .env and retry.")
        return 1
    try:
        get_embeddings()
    except MissingApiKeyError as exc:
        logger.error("%s", exc)
        return 1

    sources = [only] if only else list(BUILDERS)
    any_failed = False
    conninfo = settings.database_url.get_secret_value()
    async with await psycopg.AsyncConnection.connect(conninfo, autocommit=True) as conn:
        await register_vector_async(conn)
        for source_type in sources:
            embedded, skipped, failed = await ingest_source(
                conn, source_type, force, settings.embedding_dimensions
            )
            any_failed |= failed > 0
            print(f"{source_type:8s} embedded={embedded} skipped_existing={skipped} failed={failed}")
        print("Rows in embeddings table:", await count_by_source_type(conn))
    return 1 if any_failed else 0


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--only", choices=list(BUILDERS), help="embed one source only")
    parser.add_argument("--force", action="store_true", help="re-embed existing rows")
    args = parser.parse_args()
    sys.exit(asyncio.run(run(args.only, args.force)))


if __name__ == "__main__":
    main()
