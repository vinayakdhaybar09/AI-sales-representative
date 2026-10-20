import logging

from app.graph.builder import get_graph
from app.response.envelope import error_envelope, success_envelope
from app.schemas.chat import ChatEnvelope, ChatRequest

logger = logging.getLogger(__name__)


async def handle_chat(request: ChatRequest) -> ChatEnvelope:
    """Run the LangGraph workflow and wrap its result in the response envelope.

    M5 replaces the catch-all below with proper error classes and retries.
    """
    logger.info(
        "Chat request received (conversation_id=%s, message_length=%d)",
        request.conversation_id,
        len(request.message),
    )
    logger.debug("Message content: %s", request.message)

    try:
        state = await get_graph().ainvoke(
            {"conversation_id": request.conversation_id, "message": request.message}
        )
        return success_envelope(request.conversation_id, state["response"])
    except Exception:
        logger.exception("Chat workflow failed (conversation_id=%s)", request.conversation_id)
        return error_envelope(
            request.conversation_id,
            "internal_error",
            "Something went wrong while processing your message. Please try again.",
        )
