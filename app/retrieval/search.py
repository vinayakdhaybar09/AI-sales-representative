"""app/retrieval/search.py — vector search only (no SQL text, no LLM chat).

Embeds the query with the shared embedding model, then asks the repository
for the nearest rows of one source type. It only *discovers* candidates;
facts (price, availability, URL) always come from the products table.
"""

import logging

import psycopg

from app.core import turn_stats
from app.db.repositories.embeddings import search_by_vector
from app.llm.models import get_embeddings
from app.schemas.search import SearchHit

logger = logging.getLogger(__name__)

VALID_SOURCE_TYPES = ("product", "blog", "support")


async def search(
    conn: psycopg.AsyncConnection,
    query: str,
    source_type: str,
    k: int = 5,
) -> list[SearchHit]:
    """Return the top-k hits for `query` within a single `source_type`."""
    if source_type not in VALID_SOURCE_TYPES:
        raise ValueError(
            f"source_type must be one of {VALID_SOURCE_TYPES}, got {source_type!r}"
        )
    if not 1 <= k <= 50:
        raise ValueError("k must be between 1 and 50")

    logger.info("Vector search (source=%s, k=%d, query_len=%d)", source_type, k, len(query))
    stats = turn_stats.current()
    if stats is not None:
        stats.embed_calls += 1
    vector = await get_embeddings().aembed_query(query)
    rows = await search_by_vector(conn, source_type, vector, k)
    return [SearchHit(**row) for row in rows]
