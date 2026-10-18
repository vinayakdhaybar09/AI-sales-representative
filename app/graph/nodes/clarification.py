import logging

from app.graph.state import ChatState
from app.schemas.chat import ChatResponseBody

logger = logging.getLogger(__name__)

# M3 replaces this with one LLM-generated question + pending_clarification state.
STUB_QUESTIONS = {
    "category": "What kind of product are you looking for?",
    "products": "Which two products would you like to compare?",
    "topic": "What would you like to know about?",
}


async def clarification(state: ChatState) -> dict:
    """[STUB until M3] Ask one fixed question for the missing field."""
    logger.debug("node=clarification conversation_id=%s", state["conversation_id"])
    question = STUB_QUESTIONS.get(state.get("missing_field") or "", "Could you tell me more?")
    return {"response": ChatResponseBody(type="clarification", markdown=f"**[STUB]** {question}")}
