import logging

from app.graph.state import ChatState
from app.schemas.query import QueryUnderstanding

logger = logging.getLogger(__name__)

# Categories whose right answer depends on how the customer will use them.
# docs/PHASES.md requires "Suggest a trimmer" to ask about the use case.
CATEGORIES_NEEDING_USE_CASE = ("trimmer",)


def check_sufficiency(query: QueryUnderstanding) -> tuple[bool, str | None]:
    """Plain-Python rules from docs/ARCHITECTURE.md. Returns (sufficient, missing_field)."""
    e, f = query.entities, query.filters
    has_entity = bool(e.products or e.category or e.use_case or e.body_area or e.attributes)

    if query.intent == "recommendation":
        category = (e.category or "").lower()
        if any(word in category for word in CATEGORIES_NEEDING_USE_CASE) and not (
            e.use_case or e.body_area or e.products
        ):
            return (False, "use_case")
        has_need = bool(f.skin_type or f.hair_type or f.required_features)
        return (bool(e.category or e.use_case or e.products or has_need), "category")
    if query.intent == "comparison":
        known = set(e.products) | set(query.context.previously_mentioned_product_ids)
        return (len(known) >= 2, "products")
    if query.intent == "knowledge":
        return (has_entity, "topic")
    return (True, None)  # support: RAG handles breadth


async def sufficiency(state: ChatState) -> dict:
    """Decide whether we know enough to run a specialist.

    A message that answers our clarification is always sufficient: we clarify
    at most once per request.
    """
    if state.get("pending_resolved"):
        ok, missing = True, None
    else:
        ok, missing = check_sufficiency(state["query"])
    logger.info(
        "Sufficiency (conversation_id=%s, sufficient=%s, missing=%s)",
        state["conversation_id"], ok, None if ok else missing,
    )
    return {"sufficient": ok, "missing_field": None if ok else missing}
