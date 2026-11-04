import logging

from app.db.connection import get_pool
from app.db.repositories.products import get_products_by_ids
from app.graph import conversation_store
from app.graph.state import ChatState

logger = logging.getLogger(__name__)


async def _shown_products(stored: dict) -> list[dict]:
    """Names of the products from the last answer, so "the cream" or "the second one" can be resolved.

    Not stored (no schema change): the saved product ids are looked up in the
    `products` table. A failure only means the follow-up is resolved without names.
    """
    ids = list(stored.get("previous_product_ids") or [])
    if not ids:
        return []
    picked = set(stored.get("finalized_product_ids") or [])
    try:
        async with get_pool().connection() as conn:
            rows = await get_products_by_ids(conn, ids)
    except Exception:
        logger.warning("Could not load shown product names; continuing without them", exc_info=True)
        return []
    return [{"id": r["id"], "name": r["name"], "category": r.get("category"), "picked": r["id"] in picked} for r in rows]


async def session_loader(state: ChatState) -> dict:
    """Load this conversation's recent history from the store, plus the names of the products last shown."""
    stored = await conversation_store.load(state["conversation_id"])
    logger.debug("node=session_loader conversation_id=%s", state["conversation_id"])
    return {**stored, "shown_products": await _shown_products(stored)}
