import logging

from app.graph.state import ChatState
from app.schemas.chat import ChatResponseBody

logger = logging.getLogger(__name__)

OUT_OF_SCOPE_MARKDOWN = (
    "I can only help with Bombay Shaving Company products, grooming advice "
    "and order or policy questions. Is there something in that area I can help with?"
)
SUGGESTED_PROMPTS = ["Suggest a razor for sensitive skin", "How do I fix a patchy beard?"]


async def out_of_scope(state: ChatState) -> dict:
    """Politely decline. No product or policy claims are made."""
    logger.debug("node=out_of_scope conversation_id=%s", state["conversation_id"])
    return {
        "response": ChatResponseBody(
            type="out_of_scope",
            markdown=OUT_OF_SCOPE_MARKDOWN,
            suggested_prompts=SUGGESTED_PROMPTS,
        )
    }
