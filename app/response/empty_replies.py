"""app/response/empty_replies.py — plain replies when a specialist found nothing.

No LLM is involved: with nothing to ground a sentence on, a fixed, honest
message is safer and cheaper than a generated one. Pure logic.
"""

from app.response.suggested_prompts import pick
from app.schemas.chat import ChatResponseBody
from app.schemas.specialist import SpecialistOutput


def _contact_line(result: SpecialistOutput) -> str:
    """Tracking link / care email exactly as found in the support data (if any)."""
    contact = result.data.get("contact_info") or {}
    parts = []
    if contact.get("tracking_url"):
        parts.append(f"track an order here: {contact['tracking_url']}")
    if contact.get("care_email"):
        parts.append(f"email our care team at {contact['care_email']}")
    return ("You can " + " or ".join(parts) + ".") if parts else ""


def empty_reply(result: SpecialistOutput, seed: str) -> ChatResponseBody:
    """Deterministic response for a specialist with status 'empty'."""
    kind = result.specialist
    if kind == "recommendation":
        if "no_products_within_budget" in result.warnings:
            text = ("I couldn't find matching products within that budget. "
                    "Try a higher budget, or ask me about a different product.")
        else:
            text = ("I couldn't find a close match for that in our catalogue. "
                    "Could you describe what you need a bit differently?")
    elif kind == "comparison":
        missing = result.data.get("unresolved") or []
        if missing:
            names = ", ".join(f"“{n}”" for n in missing)
            text = (f"I couldn't find {names} in our catalogue. "
                    "Please check the product names and tell me the two products to compare.")
        else:
            text = "I need two products to compare. Which two would you like me to compare?"
    elif kind == "knowledge":
        text = ("I don't have an article on that yet. "
                "Try asking about shaving, beard care, skin care or a specific product.")
    else:
        text = ("I couldn't find that in our support information. "
                + _contact_line(result)).strip()
    return ChatResponseBody(
        type=kind, markdown=text, product_tray=[], suggested_prompts=pick(2, seed + kind)
    )
