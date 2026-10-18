"""app/graph/memory_store.py — in-memory conversation store (replaced by Postgres in M5).

Only `load` and `save` are used by the graph, so swapping the backend later
does not touch any node. State is lost on restart and never expires: fine for
development, which is why M5 exists.
"""

from typing import Any

MAX_MESSAGES = 6  # the LLM only ever sees recent history

_conversations: dict[str, dict[str, Any]] = {}


def load(conversation_id: str) -> dict[str, Any]:
    """Return {"history": [...], "previous_product_ids": [...]} (empty if new)."""
    stored = _conversations.get(conversation_id, {})
    return {
        "history": list(stored.get("history", [])),
        "previous_product_ids": list(stored.get("previous_product_ids", [])),
    }


def save(
    conversation_id: str,
    history: list[dict[str, str]],
    previous_product_ids: list[str],
) -> None:
    _conversations[conversation_id] = {
        "history": history[-MAX_MESSAGES:],
        "previous_product_ids": previous_product_ids,
    }


def clear() -> None:
    """Forget everything (used by tests/dev scripts)."""
    _conversations.clear()
