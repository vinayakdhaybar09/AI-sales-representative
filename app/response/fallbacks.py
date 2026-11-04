"""app/response/fallbacks.py — the `fallback` reply, by reason and context (pure logic).

No model call on purpose: a fallback is used when something already failed
(possibly the model itself), and a template can never invent a product fact.
The text depends on WHY we are falling back and on what the customer was asking
about, and follows the assistant's voice (docs/ARCHITECTURE.md): friendly,
brief, no emoji, at most one "!".
"""

from app.response.suggested_prompts import FALLBACK_PROMPTS
from app.schemas.chat import ChatResponseBody

UNVERIFIED = "unverified"            # the reply could not be verified after the one allowed revision
SERVICE = "service"                  # the model failed while writing the reply
SPECIALIST_ERROR = "specialist_error"  # the lookup failed

UNVERIFIED_TWO = [
    "Good question! I can't confirm the details for {a} and {b} with confidence right now, so I won't guess. "
    "I can walk you through what each one is for, or look at something else, whichever helps.",
    "Good one. I can't verify the difference between {a} and {b} right now, and I'd rather not guess. "
    "Want me to go through each one on its own, or look at something different?",
]
UNVERIFIED_ONE = [
    "Good question! I can't confirm that about {a} with confidence right now, so I won't guess. "
    "Want me to go through its main features instead, or look at something different?",
    "I can't verify that about {a} right now, and I'd rather not guess. "
    "I can go through its main features, or look at something different if you prefer.",
]
UNVERIFIED_CATEGORY = [
    "I couldn't verify that confidently, so I won't guess. Which {category} do you have in mind, or what do you need it for?",
    "I can't confirm that with confidence right now, so I'd rather not guess. "
    "Tell me which {category} you mean, or what you need it for, and I'll take another look.",
]
UNVERIFIED_NONE = [
    "I couldn't verify that confidently, so I won't guess. Could you tell me the product or category you have in mind?",
    "I can't confirm that with confidence right now. Tell me the product or category you're after and I'll take another look.",
]
SERVICE_LINES = [
    "Sorry, I hit a snag putting that together. Please try again in a moment, or ask about a specific product or category.",
    "I'm having trouble answering that right now. Could you try again in a moment?",
]
SPECIALIST_ERROR_LINES = [
    "I couldn't look that up just now. Please try again in a moment, or ask about a specific product or category.",
    "Something went wrong while I was checking that. Try again in a moment, or ask me about a specific product.",
]


def _choose(variants: list[str], seed: str) -> str:
    return variants[sum(ord(c) for c in seed) % len(variants)]


def _clean(name: str) -> str:
    return " ".join(name.split())[:80]


def fallback_text(reason: str, names: list[str], category: str | None, seed: str) -> str:
    """The reply text. `names` are product names from our own data (never from the model)."""
    names = [_clean(n) for n in names if n and n.strip()][:2]
    if reason == SERVICE:
        return _choose(SERVICE_LINES, seed)
    if reason == SPECIALIST_ERROR:
        return _choose(SPECIALIST_ERROR_LINES, seed)
    if len(names) == 2:
        return _choose(UNVERIFIED_TWO, seed).format(a=names[0], b=names[1])
    if len(names) == 1:
        return _choose(UNVERIFIED_ONE, seed).format(a=names[0])
    if category and category.strip():
        return _choose(UNVERIFIED_CATEGORY, seed).format(category=_clean(category).lower())
    return _choose(UNVERIFIED_NONE, seed)


def fallback_response(reason: str, names: list[str], category: str | None, seed: str) -> ChatResponseBody:
    """The `fallback` response (docs/CONTRACTS.md): type, empty tray and prompts are fixed, the text is not."""
    return ChatResponseBody(
        type="fallback",
        markdown=fallback_text(reason, names, category, seed),
        product_tray=[],
        suggested_prompts=list(FALLBACK_PROMPTS),
    )
