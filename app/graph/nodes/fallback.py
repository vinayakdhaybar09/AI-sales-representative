import logging

from app.graph.state import ChatState
from app.response.envelope import fallback_body

logger = logging.getLogger(__name__)


async def fallback(state: ChatState) -> dict:
    """Last resort after the one allowed retry also failed validation."""
    logger.warning("Using fallback response (conversation_id=%s)", state["conversation_id"])
    return {"response": fallback_body()}
