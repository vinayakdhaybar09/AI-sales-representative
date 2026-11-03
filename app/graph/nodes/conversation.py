import asyncio
import logging

from app.core.config import get_settings
from app.graph.state import ChatState
from app.llm.models import get_chat_model
from app.llm.prompts.conversation import build_messages
from app.llm.retry import ainvoke_with_retry
from app.response.conversation import fallback_reply, looks_like_injection, problems, tidy
from app.response.suggested_prompts import pick
from app.schemas.chat import ChatResponseBody
from app.schemas.conversation import ConversationReply

logger = logging.getLogger(__name__)

CONVERSATION_TEMPERATURE = 0.3   # a little variety so greetings do not repeat word for word


async def conversation(state: ChatState) -> dict:
    """Greetings, small talk and off-topic messages: no retrieval, no product claims.

    The model writes a short reply using the recent chat and saved preferences,
    so an off-topic question is declined *and* steered back to what the customer
    was doing. Python checks the text; on any problem, error or timeout a fixed
    line in the same voice is used, so this node never fails.
    """
    cid, message = state["conversation_id"], state["message"]
    query = state.get("query")
    off_topic_hint = bool(query and query.scope == "out_of_scope")
    off_topic = off_topic_hint

    if looks_like_injection(message):
        # No model call: a message that tries to change our role or rules gets a fixed, safe line.
        logger.info("Conversation: role/instruction change attempt, fixed line (conversation_id=%s)", cid)
        return {"response": ChatResponseBody(
            type="conversation", markdown=fallback_reply(True, message), suggested_prompts=pick(2, message))}

    try:
        async with asyncio.timeout(get_settings().conversation_timeout_seconds):
            model = get_chat_model(CONVERSATION_TEMPERATURE).with_structured_output(ConversationReply)
            result = await ainvoke_with_retry(
                model,
                build_messages(message, state.get("history", []), state.get("preferences") or {},
                               "off-topic" if off_topic_hint else "conversational"),
            )
        if not isinstance(result, ConversationReply):
            raise ValueError("conversation model returned no structured output")
        off_topic = result.kind == "off_topic"
        reply = tidy(result.reply)
        found = problems(reply)
        if found:
            logger.warning("Conversation reply rejected (%s); using a fixed line (conversation_id=%s)",
                           ", ".join(found), cid)
            reply = fallback_reply(off_topic, message)
    except Exception:
        logger.warning("Conversation model failed; using a fixed line (conversation_id=%s)", cid, exc_info=True)
        reply = fallback_reply(off_topic, message)

    logger.info("Conversation reply (conversation_id=%s, off_topic=%s, length=%d)", cid, off_topic, len(reply))
    return {
        "response": ChatResponseBody(type="conversation", markdown=reply, suggested_prompts=pick(2, message))
    }
