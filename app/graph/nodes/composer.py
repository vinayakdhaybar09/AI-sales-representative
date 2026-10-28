import logging

from app.graph.profile import describe
from app.graph.state import ChatState
from app.llm.models import get_chat_model
from app.llm.prompts.composer import build_messages
from app.llm.retry import ainvoke_with_retry
from app.response.empty_replies import empty_reply
from app.response.envelope import fallback_body
from app.response.sanitize import sanitize_markdown
from app.response.tray import build_tray
from app.schemas.chat import ChatResponseBody

logger = logging.getLogger(__name__)


async def composer(state: ChatState) -> dict:
    """Write the reply. The LLM writes Markdown only; Python builds the tray.

    - specialist 'empty'  -> fixed reply, no LLM, nothing to validate
    - specialist 'error'  -> fallback
    - otherwise           -> LLM Markdown + Python tray, sent to the validator
      (on a retry the model also sees the previous reply and the issues found)
    """
    result = state["specialist_result"]
    cid = state["conversation_id"]

    if result.status == "empty":
        logger.info("Composer: empty specialist result, fixed reply (conversation_id=%s)", cid)
        return {"response": empty_reply(result, state["message"]), "valid": True}
    if result.status == "error":
        logger.warning("Composer: specialist error, fallback (conversation_id=%s)", cid)
        return {"response": fallback_body(), "valid": True}

    attempts = state.get("composer_attempts", 0) + 1
    previous = state["response"].markdown if attempts > 1 and "response" in state else None
    try:
        reply = await ainvoke_with_retry(
            get_chat_model(),
            build_messages(
                state["search_text"], result, previous, state.get("validation_issues"),
                state.get("history"), describe(state.get("profile") or {}),
            ),
            f"composer{attempts}",
        )
        markdown = sanitize_markdown(reply.text)   # .text joins the text blocks (Gemini returns a list of blocks)
    except Exception:
        logger.exception("Composer LLM call failed (conversation_id=%s)", cid)
        return {"response": fallback_body(), "valid": True, "composer_attempts": attempts}

    logger.info("Composer attempt %d done (conversation_id=%s, markdown_length=%d)", attempts, cid, len(markdown))
    return {
        "response": ChatResponseBody(type=result.specialist, markdown=markdown, product_tray=build_tray(result)),
        "composer_attempts": attempts,
        "valid": False,   # not valid until the validator says so
    }
