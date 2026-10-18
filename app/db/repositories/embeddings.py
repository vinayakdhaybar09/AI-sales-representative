"""app/db/repositories/embeddings.py — SQL-only access to the embeddings table.

Layering rule: SQL and nothing else. Callers pass a psycopg AsyncConnection
(with pgvector adapters registered) and own the transaction.
"""

import json
from typing import Any

import psycopg
from pgvector import Vector
from psycopg.rows import dict_row


async def existing_source_ids(
    conn: psycopg.AsyncConnection, source_type: str
) -> set[str]:
    """IDs already stored for a source type (lets ingestion resume)."""
    cur = await conn.execute(
        "SELECT source_id FROM embeddings WHERE source_type = %s", (source_type,)
    )
    return {row[0] for row in await cur.fetchall()}


async def upsert_embedding(
    conn: psycopg.AsyncConnection,
    source_type: str,
    source_id: str,
    content: str,
    metadata: dict[str, Any],
    embedding: list[float],
) -> None:
    """Insert or update one row, keyed on (source_type, source_id)."""
    await conn.execute(
        """
        INSERT INTO embeddings (source_type, source_id, content, metadata, embedding)
        VALUES (%s, %s, %s, %s::jsonb, %s)
        ON CONFLICT (source_type, source_id) DO UPDATE SET
            content   = EXCLUDED.content,
            metadata  = EXCLUDED.metadata,
            embedding = EXCLUDED.embedding
        """,
        (source_type, source_id, content, json.dumps(metadata), Vector(embedding)),
    )


async def count_by_source_type(conn: psycopg.AsyncConnection) -> dict[str, int]:
    cur = await conn.execute(
        "SELECT source_type, count(*) FROM embeddings GROUP BY source_type"
    )
    return {row[0]: row[1] for row in await cur.fetchall()}


async def search_by_vector(
    conn: psycopg.AsyncConnection,
    source_type: str,
    query_embedding: list[float],
    k: int,
) -> list[dict[str, Any]]:
    """Top-k nearest rows of ONE source type by cosine distance (`<=>`).

    Always filtered by source_type: sources are never mixed in one search.
    """
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(
            """
            SELECT source_type, source_id, content, metadata,
                   1 - (embedding <=> %s) AS score
            FROM embeddings
            WHERE source_type = %s AND embedding IS NOT NULL
            ORDER BY embedding <=> %s
            LIMIT %s
            """,
            (Vector(query_embedding), source_type, Vector(query_embedding), k),
        )
        return await cur.fetchall()


async def find_support_contact_rows(conn: psycopg.AsyncConnection) -> list[str]:
    """Support texts that mention an email address or a tracking link.

    Used to hand back the care email / tracking link exactly as written in the
    data, even when the semantic search did not retrieve those rows.
    """
    cur = await conn.execute(
        "SELECT content FROM embeddings WHERE source_type = 'support' "
        "AND (content ILIKE '%@%' OR content ILIKE '%track%') ORDER BY source_id"
    )
    return [row[0] for row in await cur.fetchall()]
