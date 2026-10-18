import logging

from app.graph.state import ChatState
from app.schemas.chat import ChatResponseBody

logger = logging.getLogger(__name__)


async def composer(state: ChatState) -> dict:
    """[STUB until M4] Echoes which specialist ran; the tray stays empty."""
    result = state["specialist_result"]
    q = state["query"]
    logger.debug("node=composer conversation_id=%s", state["conversation_id"])
    return {
        "response": ChatResponseBody(
            type=result.specialist,
            markdown=(
                f"**[STUB]** `{result.specialist}` specialist would answer here "
                f"(category: {q.entities.category}, products: {q.entities.products})."
            ),
        )
    }
