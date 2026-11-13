"""app/db/repositories/support_queries.py — SQL-only access to the support_queries table."""

from typing import Any

import psycopg
from psycopg.types.json import Jsonb


async def insert_query(
    conn: psycopg.AsyncConnection,
    conversation_id: str,
    idempotency_key: str,
    category: str,
    description: str,
    details: dict[str, Any],
    attachments_meta: list[dict[str, Any]],
) -> str:
    """Store one query and return its reference. Sending the same idempotency key again returns the first row's reference."""
    cur = await conn.execute(
        """
        INSERT INTO support_queries
            (conversation_id, idempotency_key, category, description, details, attachments_meta)
        VALUES (%s, %s, %s, %s, %s, %s)
        ON CONFLICT (idempotency_key) DO UPDATE SET idempotency_key = EXCLUDED.idempotency_key
        RETURNING ref
        """,
        (conversation_id, idempotency_key, category, description, Jsonb(details), Jsonb(attachments_meta)),
    )
    row = await cur.fetchone()
    return row[0]
