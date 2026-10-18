import logging

from app.graph import memory_store
from app.graph.state import ChatState

logger = logging.getLogger(__name__)


async def session_loader(state: ChatState) -> dict:
    """Load this conversation's recent history from the store."""
    stored = memory_store.load(state["conversation_id"])
    logger.debug("node=session_loader conversation_id=%s", state["conversation_id"])
    return stored
