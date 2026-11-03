import logging

from app.graph import preferences as prefs_memory
from app.graph.state import ChatState
from app.llm.models import get_chat_model
from app.llm.prompts.query_understanding import build_messages
from app.llm.retry import ainvoke_with_retry
from app.schemas.query import QueryUnderstanding

logger = logging.getLogger(__name__)

MAX_REQUIREMENTS = 6


async def understand(
    message: str,
    history: list[dict[str, str]],
    pending: dict | None = None,
    preferences: dict | None = None,
) -> QueryUnderstanding:
    """Ask the chat model for a structured reading of `message`."""
    model = get_chat_model().with_structured_output(QueryUnderstanding)
    result = await ainvoke_with_retry(model, build_messages(message, history, pending, preferences))
    if not isinstance(result, QueryUnderstanding):
        raise ValueError("Query Understanding returned no structured output")
    return result


async def query_understanding(state: ChatState) -> dict:
    """LLM step: extract {intent, scope, entities, filters, context}.

    Also settles any open clarification: either this message answers it
    (retrieval then uses original request + answer, and we never ask again) or
    it is a new request and the pending question is dropped.
    """
    pending = state.get("pending_clarification")
    query = await understand(
        state["message"], state.get("history", []), pending, state.get("preferences")
    )
    # Product IDs come from our own state, never from the LLM.
    query.context.previously_mentioned_product_ids = list(state.get("previous_product_ids", []))

    resolved = bool(
        pending and query.scope == "in_scope" and query.context.answers_pending_clarification
    )
    search_text = state["message"]
    if resolved:
        query.intent = pending["intent"]  # an answer never changes the original intent
        if query.intent == "product_finalization" and query.filters.result_limit is None:
            query.filters.result_limit = pending.get("result_limit")   # "just one" survives the question
        search_text = f"{pending['original_query']}. {state['message']}"

    # Always leave the later stages a usable standalone request and a short requirement list.
    query.resolved_request = query.resolved_request.strip() or search_text
    query.requirements = [r.strip() for r in query.requirements if r and r.strip()][:MAX_REQUIREMENTS]

    logger.info(
        "Query understood (conversation_id=%s, intent=%s, scope=%s, resumed=%s)",
        state["conversation_id"], query.intent, query.scope, resolved,
    )
    # Structured memory: only real, in-scope requests teach us about the customer.
    preferences = state.get("preferences") or {}
    if query.scope == "in_scope":
        preferences = prefs_memory.merge(preferences, query)

    return {
        "query": query,
        "preferences": preferences,
        "pending_resolved": resolved,
        "search_text": search_text,
        "pending_clarification": None,   # settled either way; clarification may set a new one
    }
