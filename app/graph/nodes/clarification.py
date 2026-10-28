import logging
import re

from app.graph.state import ChatState
from app.llm.models import get_chat_model
from app.llm.prompts.clarification import build_messages, fallback_question
from app.llm.retry import ainvoke_with_retry
from app.schemas.chat import ChatResponseBody
from app.schemas.query import Clarification

logger = logging.getLogger(__name__)


async def _ask_llm(original_query: str, intent: str, missing_field: str) -> str:
    model = get_chat_model().with_structured_output(Clarification)
    result = await ainvoke_with_retry(model, build_messages(original_query, intent, missing_field), "clarification")
    question = result.question.strip()
    # Exactly one question: cut anything after the first '?'.
    match = re.match(r"[^?]*\?", question)
    return match.group(0).strip() if match else question


async def clarification(state: ChatState) -> dict:
    """Ask ONE question and remember it as pending_clarification.

    If the model call fails we fall back to a fixed question for the missing
    field, so the user is never left without an answer.
    """
    query = state["query"]
    missing = state.get("missing_field") or "topic"
    try:
        question = await _ask_llm(state["message"], query.intent, missing)
    except Exception:
        logger.warning("Clarification LLM failed; using fixed question", exc_info=True)
        question = fallback_question(missing)
    if not question:
        question = fallback_question(missing)

    pending = {
        "original_query": state["message"],
        "intent": query.intent,
        "missing_field": missing,
        "question": question,
        "attempt_count": 1,
    }
    logger.info("Clarification asked (conversation_id=%s, missing=%s)", state["conversation_id"], missing)
    return {
        "pending_clarification": pending,
        "response": ChatResponseBody(type="clarification", markdown=question),
    }
