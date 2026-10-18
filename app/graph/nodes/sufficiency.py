import logging

from app.graph.state import ChatState
from app.schemas.query import QueryUnderstanding

logger = logging.getLogger(__name__)


def check_sufficiency(query: QueryUnderstanding) -> tuple[bool, str | None]:
    """Plain-Python rules from docs/ARCHITECTURE.md. Returns (sufficient, missing_field)."""
    e, f = query.entities, query.filters
    has_entity = bool(e.products or e.category or e.use_case or e.body_area or e.attributes)

    if query.intent == "recommendation":
        has_need = bool(f.skin_type or f.hair_type or f.required_features)
        return (bool(e.category or e.use_case or e.products or has_need), "category")
    if query.intent == "comparison":
        known = set(e.products) | set(query.context.previously_mentioned_product_ids)
        return (len(known) >= 2, "products")
    if query.intent == "knowledge":
        return (has_entity, "topic")
    return (True, None)  # support: RAG handles breadth


async def sufficiency(state: ChatState) -> dict:
    """Decide whether we know enough to run a specialist."""
    ok, missing = check_sufficiency(state["query"])
    logger.info(
        "Sufficiency (conversation_id=%s, sufficient=%s, missing=%s)",
        state["conversation_id"], ok, None if ok else missing,
    )
    return {"sufficient": ok, "missing_field": None if ok else missing}
