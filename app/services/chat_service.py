import logging

from app.graph.builder import get_graph
from app.schemas.chat import ChatEnvelope, ChatRequest, ErrorInfo

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
        return ChatEnvelope(
            success=True,
            conversation_id=request.conversation_id,
            response=state["response"],
            error=None,
        )
    except Exception:
        logger.exception("Chat workflow failed (conversation_id=%s)", request.conversation_id)
        return ChatEnvelope(
            success=False,
            conversation_id=request.conversation_id,
            response=None,
            error=ErrorInfo(
                code="internal_error",
                message="Something went wrong while processing your message. Please try again.",
            ),
        )
