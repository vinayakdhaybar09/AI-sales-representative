"""app/graph/conversation_store.py — conversation state in Postgres.

The graph only uses `load` and `save`. Storage trouble must never stop a user
from getting an answer: a failed load means "treat as a new conversation", a
failed save is logged and skipped.
"""

import logging
from typing import Any

from app.core.config import get_settings
from app.db.connection import get_pool
from app.db.repositories import conversations

logger = logging.getLogger(__name__)

MAX_MESSAGES = 6  # the LLM only ever sees recent history


def _empty() -> dict[str, Any]:
    return {"history": [], "previous_product_ids": [], "pending_clarification": None}


async def load(conversation_id: str) -> dict[str, Any]:
    """history, previous_product_ids and pending_clarification (empty if new/expired)."""
    ttl = get_settings().conversation_ttl_minutes
    try:
        async with get_pool().connection() as conn:
            stored = await conversations.get_conversation(conn, conversation_id, ttl)
    except Exception:
        logger.warning("Could not load conversation (conversation_id=%s); starting fresh",
                       conversation_id, exc_info=True)
        return _empty()
    return stored or _empty()


async def save(
    conversation_id: str,
    history: list[dict[str, str]],
    previous_product_ids: list[str],
    pending_clarification: dict[str, Any] | None,
) -> None:
    """Persist this turn and purge conversations that have expired."""
    ttl = get_settings().conversation_ttl_minutes
    try:
        async with get_pool().connection() as conn:
            await conversations.upsert_conversation(
                conn, conversation_id, history[-MAX_MESSAGES:], previous_product_ids, pending_clarification
            )
            await conversations.delete_expired(conn, ttl)
    except Exception:
        logger.warning("Could not save conversation (conversation_id=%s); continuing",
                       conversation_id, exc_info=True)
