"""scripts/search_dev.py — try vector search from the terminal.

Usage:
    python -m scripts.search_dev "patchy beard" --source blog -k 5
"""

import argparse
import asyncio
import sys

import psycopg
from pgvector.psycopg import register_vector_async

from app.core.config import get_settings
from app.core.logging import setup_logging
from app.retrieval.search import VALID_SOURCE_TYPES, search

setup_logging()


async def run(query: str, source: str, k: int) -> int:
    settings = get_settings()
    if not settings.database_url:
        print("DATABASE_URL is not set. Add it to .env and retry.")
        return 1
    async with await psycopg.AsyncConnection.connect(
        settings.database_url.get_secret_value()
    ) as conn:
        await register_vector_async(conn)
        hits = await search(conn, query, source, k)
    for rank, hit in enumerate(hits, 1):
        preview = hit.content.replace("\n", " ")[:90]
        print(f"{rank}. [{hit.source_type}] {hit.source_id}  score={hit.score:.3f}  {preview}")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("query")
    parser.add_argument("--source", required=True, choices=VALID_SOURCE_TYPES)
    parser.add_argument("-k", type=int, default=5)
    args = parser.parse_args()
    sys.exit(asyncio.run(run(args.query, args.source, args.k)))


if __name__ == "__main__":
    main()
