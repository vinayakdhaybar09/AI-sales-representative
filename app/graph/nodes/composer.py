import logging

from app.graph.state import ChatState
from app.schemas.chat import ChatResponseBody
from app.schemas.specialist import SpecialistOutput

logger = logging.getLogger(__name__)


def _summary(result: SpecialistOutput) -> str:
    """Plain list of what the specialist found (stand-in for real prose)."""
    d = result.data
    lines: list[str] = []
    for p in d.get("products", []):
        lines.append(f"- {p['name']} (Rs {p['price']}, {p['availability']})")
    for c in d.get("chunks", []):
        lines.append(f"- article: {c['title']} / {c['heading']}")
    for i in d.get("items", []):
        lines.append(f"- {i['source_id']}: {i['content'].splitlines()[0][:80]}")
    contact = d.get("contact_info")
    if contact:
        lines.append(f"- contact: {contact['tracking_url']} | {contact['care_email']}")
    if result.warnings:
        lines.append(f"- warnings: {', '.join(result.warnings)}")
    return "\n".join(lines) or "- (nothing found)"


async def composer(state: ChatState) -> dict:
    """[STUB until M4] Lists the specialist output; no real writing, empty tray."""
    result = state["specialist_result"]
    logger.debug("node=composer conversation_id=%s", state["conversation_id"])
    return {
        "response": ChatResponseBody(
            type=result.specialist,
            markdown=f"**[STUB]** `{result.specialist}` -> {result.status}\n{_summary(result)}",
        )
    }
