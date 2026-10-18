import logging

from app.graph.state import ChatState
from app.llm.models import get_chat_model
from app.llm.prompts.query_understanding import build_messages
from app.llm.retry import ainvoke_with_429_retry
from app.schemas.query import QueryUnderstanding

logger = logging.getLogger(__name__)


async def understand(message: str, history: list[dict[str, str]]) -> QueryUnderstanding:
    """Ask the chat model for a structured reading of `message`."""
    model = get_chat_model().with_structured_output(QueryUnderstanding)
    result = await ainvoke_with_429_retry(model, build_messages(message, history))
    if not isinstance(result, QueryUnderstanding):
        raise ValueError("Query Understanding returned no structured output")
    return result


async def query_understanding(state: ChatState) -> dict:
    """LLM step: extract {intent, scope, entities, filters, context}."""
    query = await understand(state["message"], state.get("history", []))
    # Product IDs come from our own state, never from the LLM.
    query.context.previously_mentioned_product_ids = list(state.get("previous_product_ids", []))
    logger.info(
        "Query understood (conversation_id=%s, intent=%s, scope=%s)",
        state["conversation_id"], query.intent, query.scope,
    )
    return {"query": query}
