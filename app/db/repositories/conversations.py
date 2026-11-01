"""app/db/repositories/conversations.py — SQL-only access to the conversations table."""

from typing import Any

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb


async def get_conversation(
    conn: psycopg.AsyncConnection, conversation_id: str, ttl_minutes: float
) -> dict[str, Any] | None:
    """Return the stored conversation, or None if it is new or has expired.

    An expired row (idle longer than ttl_minutes) is deleted on the spot.
    """
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(
            """
            SELECT history, previous_product_ids, pending_clarification,
                   pool_search_text, pool_match_scores, finalized_product_ids, preferences,
                   updated_at < now() - interval '1 minute' * %s AS expired
            FROM conversations WHERE conversation_id = %s
            """,
            (ttl_minutes, conversation_id),
        )
        row = await cur.fetchone()
        if row is None:
            return None
        if row.pop("expired"):
            await cur.execute("DELETE FROM conversations WHERE conversation_id = %s", (conversation_id,))
            return None
        return row


async def upsert_conversation(
    conn: psycopg.AsyncConnection,
    conversation_id: str,
    history: list[dict[str, str]],
    previous_product_ids: list[str],
    pending_clarification: dict[str, Any] | None,
    pool_search_text: str | None = None,
    pool_match_scores: dict[str, float] | None = None,
    finalized_product_ids: list[str] | None = None,
    preferences: dict[str, Any] | None = None,
) -> None:
    """Insert or update a conversation and refresh its idle timer."""
    await conn.execute(
        """
        INSERT INTO conversations
            (conversation_id, history, previous_product_ids, pending_clarification,
             pool_search_text, pool_match_scores, finalized_product_ids, preferences, updated_at)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, now())
        ON CONFLICT (conversation_id) DO UPDATE SET
            history               = EXCLUDED.history,
            previous_product_ids  = EXCLUDED.previous_product_ids,
            pending_clarification = EXCLUDED.pending_clarification,
            pool_search_text      = EXCLUDED.pool_search_text,
            pool_match_scores     = EXCLUDED.pool_match_scores,
            finalized_product_ids = EXCLUDED.finalized_product_ids,
            preferences           = EXCLUDED.preferences,
            updated_at            = now()
        """,
        (
            conversation_id,
            Jsonb(history),
            Jsonb(previous_product_ids),
            Jsonb(pending_clarification) if pending_clarification is not None else None,
            pool_search_text,
            Jsonb(pool_match_scores or {}),
            Jsonb(finalized_product_ids or []),
            Jsonb(preferences or {}),
        ),
    )


async def delete_expired(conn: psycopg.AsyncConnection, ttl_minutes: float) -> int:
    """Delete every conversation idle longer than ttl_minutes; returns how many."""
    cur = await conn.execute(
        "DELETE FROM conversations WHERE updated_at < now() - interval '1 minute' * %s",
        (ttl_minutes,),
    )
    return cur.rowcount
