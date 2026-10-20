import asyncio
import logging

from app.core.config import get_settings
from app.core.errors import INTERNAL_ERROR, classify
from app.graph.builder import get_graph
from app.response.envelope import error_envelope, success_envelope
from app.schemas.chat import ChatEnvelope, ChatRequest

logger = logging.getLogger(__name__)


async def handle_chat(request: ChatRequest) -> ChatEnvelope:
    """Run the LangGraph workflow and wrap its result in the response envelope.

    Any failure is turned into a client-safe error envelope (see app/core/errors.py);
    stack traces go to the log only.
    """
    logger.info(
        "Chat request received (conversation_id=%s, message_length=%d)",
        request.conversation_id,
        len(request.message),
    )
    logger.debug("Message content: %s", request.message)

    try:
        async with asyncio.timeout(get_settings().request_timeout_seconds):
            state = await get_graph().ainvoke(
                {"conversation_id": request.conversation_id, "message": request.message}
            )
        return success_envelope(request.conversation_id, state["response"])
    except Exception as exc:
        err = classify(exc)
        if err.code == INTERNAL_ERROR:
            logger.exception("Chat workflow failed (conversation_id=%s)", request.conversation_id)
        else:
            logger.warning("Chat request failed: %s (conversation_id=%s, cause=%s)",
                           err.code, request.conversation_id, type(exc).__name__)
        return error_envelope(request.conversation_id, err.code, err.message)
