import logging

from app.graph.state import ChatState
from app.schemas.specialist import SpecialistOutput

logger = logging.getLogger(__name__)


def _stub(name: str):
    async def node(state: ChatState) -> dict:
        """[STUB until M3] Returns the right output shape with no data."""
        logger.debug("node=specialist_%s conversation_id=%s", name, state["conversation_id"])
        return {
            "specialist_result": SpecialistOutput(
                specialist=name, status="empty", warnings=["stub_specialist"]
            )
        }

    node.__name__ = f"specialist_{name}"
    return node


specialist_recommendation = _stub("recommendation")
specialist_comparison = _stub("comparison")
specialist_knowledge = _stub("knowledge")
specialist_support = _stub("support")
