import logging

from app.graph import conversation_store
from app.graph.state import ChatState
from app.schemas.chat import ChatResponseBody

logger = logging.getLogger(__name__)

MAX_STORED_REPLY_CHARS = 400


def _history_text(response: ChatResponseBody) -> str:
    """What the assistant's turn looks like in stored history.

    A full product answer is long and the products are already in the tray, so
    we keep just who was shown (cheaper for the LLM, and enough context).
    """
    cards = response.product_tray or (response.comparison_table.products if response.comparison_table else [])
    if cards:
        names = ", ".join(f"{c.name} (₹{c.price:g})" for c in cards)
        label = {"product_finalization": "Picked as the best option", "comparison": "Compared"}.get(response.type, "Showed products")
        return f"{label}: {names}"
    text = response.markdown
    return text if len(text) <= MAX_STORED_REPLY_CHARS else text[:MAX_STORED_REPLY_CHARS].rsplit(" ", 1)[0] + "…"


async def finalize(state: ChatState) -> dict:
    """Save this turn (history, product pool, latest pick, preferences, pending clarification)."""
    response = state["response"]
    history = list(state.get("history", []))
    history.append({"role": "user", "content": state["message"]})
    history.append({"role": "assistant", "content": _history_text(response)})

    shown = [card.product_id for card in response.product_tray]
    result = state.get("specialist_result")
    pool_ids = state.get("previous_product_ids", [])
    pool_text = state.get("pool_search_text")
    pool_scores = state.get("pool_match_scores") or {}
    finalized = state.get("finalized_product_ids", [])

    if response.type == "recommendation" and shown and result:
        # A new list becomes the pool that "narrow it down" will pick from.
        pool_ids, pool_text, finalized = shown, state.get("search_text"), []
        pool_scores = {str(p["id"]): p["match_score"] for p in result.data.get("products", [])}
    elif response.type == "product_finalization" and shown and result:
        finalized = shown
        if result.data.get("pool_source") == "new_search":   # we had to search: that is the new pool
            pool_ids = [c["id"] for c in result.data["pool"]]
            pool_scores = {c["id"]: c["match_score"] for c in result.data["pool"]}
            pool_text = state.get("search_text")
        # else: keep the existing pool, so the customer can narrow down again

    await conversation_store.save(
        state["conversation_id"], history, pool_ids, state.get("pending_clarification"),
        pool_search_text=pool_text,
        pool_match_scores=pool_scores,
        finalized_product_ids=finalized,
        preferences=state.get("preferences"),
    )
    logger.debug("node=finalize conversation_id=%s", state["conversation_id"])
    return {}
