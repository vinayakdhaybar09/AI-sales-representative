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

MAX_MESSAGES = 12  # the LLM only ever sees recent history (assistant turns are stored compactly)


def _empty() -> dict[str, Any]:
    return {
        "history": [], "previous_product_ids": [], "pending_clarification": None,
        "pool_search_text": None, "pool_match_scores": {}, "finalized_product_ids": [], "preferences": {},
    }


async def load(conversation_id: str) -> dict[str, Any]:
    """Everything saved for this conversation (an empty state if new/expired)."""
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
    *,
    pool_search_text: str | None = None,
    pool_match_scores: dict[str, float] | None = None,
    finalized_product_ids: list[str] | None = None,
    preferences: dict[str, Any] | None = None,
) -> None:
    """Persist this turn and purge conversations that have expired."""
    ttl = get_settings().conversation_ttl_minutes
    try:
        async with get_pool().connection() as conn:
            await conversations.upsert_conversation(
                conn, conversation_id, history[-MAX_MESSAGES:], previous_product_ids, pending_clarification,
                pool_search_text, pool_match_scores, finalized_product_ids, preferences,
            )
            await conversations.delete_expired(conn, ttl)
    except Exception:
        logger.warning("Could not save conversation (conversation_id=%s); continuing",
                       conversation_id, exc_info=True)


async def add_assistant_note(conversation_id: str, text: str) -> None:
    """Append one assistant line to an existing conversation (used after a query is submitted).

    A conversation that no longer exists is left alone, and any storage problem is logged and skipped.
    """
    stored = await load(conversation_id)
    if not stored.get("history"):
        return
    await save(
        conversation_id,
        [*stored["history"], {"role": "assistant", "content": text}],
        stored.get("previous_product_ids", []),
        stored.get("pending_clarification"),
        pool_search_text=stored.get("pool_search_text"),
        pool_match_scores=stored.get("pool_match_scores"),
        finalized_product_ids=stored.get("finalized_product_ids"),
        preferences=stored.get("preferences"),
    )
