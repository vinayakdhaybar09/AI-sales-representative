import logging

from app.graph.state import ChatState
from app.response.envelope import fallback_body

logger = logging.getLogger(__name__)


async def fallback(state: ChatState) -> dict:
    """Last resort after the one allowed retry also failed validation.

    A failed turn must not lose the open question: if the customer was answering a
    clarification, it stays pending so their next message can still be matched to it."""
    logger.warning("Using fallback response (conversation_id=%s)", state["conversation_id"])
    return {"response": fallback_body(), "pending_clarification": state.get("pending_before")}
