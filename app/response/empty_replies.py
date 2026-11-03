"""app/response/empty_replies.py — plain replies when a specialist found nothing.

No LLM is involved: with nothing to ground a sentence on, a fixed, honest
message is safer and cheaper than a generated one. They are written in the
assistant's voice (docs/ARCHITECTURE.md): friendly, brief, no hype, no emoji,
and each kind has two variants picked deterministically from the message.
Pure logic.
"""

from app.response.suggested_prompts import pick
from app.schemas.chat import ChatResponseBody
from app.schemas.specialist import SpecialistOutput

NO_MATCH = [
    "I couldn't find a close match for that in our range. Could you tell me a bit more about what you need, or describe it another way?",
    "Hmm, nothing in our range matches that closely. Tell me what it's for or what matters most, and I'll have another look.",
]
NO_MATCH_BUDGET = [
    "I couldn't find a match within that budget. Want to try a slightly higher one, or shall I look at something different?",
    "Nothing we have fits that budget right now. If you can stretch it a little, or tell me what matters most, I'll look again.",
]
NO_PICK = [
    "None of the products I have fit all of those requirements. Want to relax one of them, or shall I suggest something new?",
    "I couldn't find a pick that meets all of that. If you loosen one requirement, I'll look again.",
]
NO_PICK_BUDGET = [
    "I couldn't find a good pick within that budget. Try a higher budget, or ask me for other suggestions.",
    "Nothing I'd confidently pick fits that budget. Want me to look a bit higher, or at something different?",
]
COMPARE_UNKNOWN = [
    "I couldn't find {names} in our range. Could you check the names and tell me the two products you'd like me to compare?",
    "I can't find {names} in our range. Which two products would you like me to compare? The exact names help.",
]
COMPARE_NEED_TWO = [
    "Happy to compare. Which two products would you like me to look at?",
    "Sure, tell me the two products you want side by side and I'll compare them.",
]
NO_GUIDE = [
    "I don't have a guide on that yet, but I'm happy to help with shaving, beard care, skin care or a specific product.",
    "That one isn't covered in our guides yet. Ask me about shaving, beard care, skin care or a product and I'll help.",
]
NO_SUPPORT = [
    "I couldn't find that in our support information.",
    "I don't have a clear answer to that in our support information.",
]


def _contact_line(result: SpecialistOutput) -> str:
    """Tracking link / care email exactly as found in the support data (if any)."""
    contact = result.data.get("contact_info") or {}
    parts = []
    if contact.get("tracking_url"):
        parts.append(f"track an order here: {contact['tracking_url']}")
    if contact.get("care_email"):
        parts.append(f"email our care team at {contact['care_email']}")
    return ("You can " + " or ".join(parts) + ".") if parts else ""


def _choose(variants: list[str], seed: str) -> str:
    return variants[sum(ord(c) for c in seed) % len(variants)]


def empty_reply(result: SpecialistOutput, seed: str) -> ChatResponseBody:
    """Deterministic response for a specialist with status 'empty'."""
    kind = result.specialist
    over_budget = "no_products_within_budget" in result.warnings
    if kind == "recommendation":
        text = _choose(NO_MATCH_BUDGET if over_budget else NO_MATCH, seed)
    elif kind == "product_finalization":
        text = _choose(NO_PICK_BUDGET if over_budget else NO_PICK, seed)
    elif kind == "comparison":
        missing = result.data.get("unresolved") or []
        if missing:
            names = ", ".join(f"“{n}”" for n in missing)
            text = _choose(COMPARE_UNKNOWN, seed).format(names=names)
        else:
            text = _choose(COMPARE_NEED_TWO, seed)
    elif kind == "knowledge":
        text = _choose(NO_GUIDE, seed)
    else:
        text = f"{_choose(NO_SUPPORT, seed)} {_contact_line(result)}".strip()
    return ChatResponseBody(
        type=kind, markdown=text, product_tray=[], suggested_prompts=pick(2, seed + kind)
    )
