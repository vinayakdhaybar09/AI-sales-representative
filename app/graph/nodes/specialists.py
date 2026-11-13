"""Graph nodes for the four specialists.

A node only fetches a connection and calls the specialist; all retrieval logic
lives in app/specialists/. If a specialist raises, we return status="error" so
the flow continues (M4's Composer/fallback decides what to tell the user).
"""

import logging

from app.db.connection import get_pool
from app.graph.state import ChatState
from app.schemas.specialist import SpecialistOutput
from app.graph.preferences import apply_to_query
from app.specialists import comparison, finalization, knowledge, query_submission, recommendation, support

logger = logging.getLogger(__name__)


def _node(name: str, call):
    async def node(state: ChatState) -> dict:
        logger.debug("node=specialist_%s conversation_id=%s", name, state["conversation_id"])
        try:
            async with get_pool().connection() as conn:
                result = await call(conn, state)
        except Exception:
            logger.exception("Specialist %s failed (conversation_id=%s)", name, state["conversation_id"])
            result = SpecialistOutput(specialist=name, status="error", warnings=["specialist_failed"])
        logger.info("Specialist %s -> %s (conversation_id=%s)", name, result.status, state["conversation_id"])
        return {"specialist_result": result}

    node.__name__ = f"specialist_{name}"
    return node


specialist_recommendation = _node(
    "recommendation", lambda conn, s: recommendation.run(conn, s["query"], s["search_text"])
)
specialist_product_finalization = _node(
    "product_finalization",
    # The customer's saved preferences fill any gaps in what they said this turn.
    lambda conn, s: finalization.run(
        conn,
        apply_to_query(s["query"], s.get("preferences") or {}),
        s["search_text"],
        s.get("previous_product_ids", []),
        s.get("pool_match_scores") or {},
    ),
)
specialist_comparison = _node(
    "comparison",
    lambda conn, s: comparison.run(conn, s["query"], s.get("previous_product_ids", []), s.get("shown_products")),
)
specialist_knowledge = _node(
    "knowledge", lambda conn, s: knowledge.run(conn, s["query"], s["search_text"])
)
specialist_support = _node(
    "support", lambda conn, s: support.run(conn, s["query"], s["search_text"])
)
specialist_query_submission = _node(
    "query_submission", lambda conn, s: query_submission.run(s["query"], s["message"])
)
