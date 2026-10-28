import logging

from app.graph.state import ChatState
from app.response.suggested_prompts import pick
from app.schemas.chat import ChatResponseBody

logger = logging.getLogger(__name__)

WELCOME = (
    "Hi! Welcome to Bombay Shaving Company. I'm here to help you find the right grooming products "
    "and answer any questions. What are you looking for today?"
)
WELCOME_BACK = "Hi again! What can I help you find?"
THANKS = "You're welcome! If you'd like to look at anything else, I'm happy to help."


async def greeting(state: ChatState) -> dict:
    """Greeting or thanks: a warm fixed reply, no model call. Open-ended, so the customer leads."""
    kind = state["query"].context.smalltalk
    if kind == "thanks":
        text = THANKS
    else:
        text = WELCOME_BACK if state.get("history") else WELCOME
    logger.debug("node=greeting conversation_id=%s kind=%s", state["conversation_id"], kind)
    # type "knowledge" keeps the response contract unchanged for the frontend
    return {"response": ChatResponseBody(type="knowledge", markdown=text, suggested_prompts=pick(3, state["message"]))}
