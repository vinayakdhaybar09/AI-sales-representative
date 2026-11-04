import logging

from app.graph.state import ChatState
from app.response.fallbacks import UNVERIFIED, fallback_response
from app.schemas.chat import ChatResponseBody

logger = logging.getLogger(__name__)

PRODUCT_INTENTS = ("comparison", "product_finalization", "recommendation")


def build_fallback(state: ChatState, reason: str) -> ChatResponseBody:
    """A fallback that knows why it happened and what the customer was asking about.

    Product names come from the customer's resolved request (or, for a comparison,
    the products just shown); a support or knowledge question never gets product names.
    """
    query = state.get("query")
    names: list[str] = []
    category = None
    if query is not None and query.intent in PRODUCT_INTENTS:
        names = list(query.entities.products)
        if not names and query.intent == "comparison":
            names = [p["name"] for p in state.get("shown_products") or []]
        if query.intent != "comparison":
            category = (state.get("preferences") or {}).get("category")
    return fallback_response(reason, names, category, state.get("message", ""))


async def fallback(state: ChatState) -> dict:
    """Last resort after the one allowed revision also failed validation."""
    reason = state.get("fallback_reason") or UNVERIFIED
    logger.warning("Using fallback response (conversation_id=%s, reason=%s)", state["conversation_id"], reason)
    return {"response": build_fallback(state, reason)}
