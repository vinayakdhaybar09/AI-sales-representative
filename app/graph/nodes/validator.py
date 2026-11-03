import logging

from app.db.connection import get_pool
from app.db.repositories.products import get_all_product_names
from app.graph.state import ChatState
from app.response.validator import validate

logger = logging.getLogger(__name__)

_catalog_names: list[str] | None = None


async def _get_catalog_names() -> list[str]:
    """Product names from Postgres, loaded once (used to spot mixed-up products)."""
    global _catalog_names
    if _catalog_names is None:
        try:
            async with get_pool().connection() as conn:
                _catalog_names = await get_all_product_names(conn)
        except Exception:
            logger.warning("Could not load catalog names; skipping the mixed-up-product check", exc_info=True)
            return []
    return _catalog_names


async def validator(state: ChatState) -> dict:
    """Deterministic check of the composed response against the specialist output."""
    query = state.get("query")
    request_text = f"{state.get('message', '')} {query.resolved_request if query else ''}"
    check = validate(state["response"], state["specialist_result"], await _get_catalog_names(), request_text)
    cid = state["conversation_id"]
    for note in check.non_critical:
        logger.info("Validator note (conversation_id=%s): %s", cid, note)
    if check.valid:
        logger.info("Validation passed (conversation_id=%s)", cid)
    else:
        logger.warning("Validation failed (conversation_id=%s, attempt=%s): %s",
                       cid, state.get("composer_attempts"), "; ".join(check.critical))
    return {"valid": check.valid, "validation_issues": check.critical}
