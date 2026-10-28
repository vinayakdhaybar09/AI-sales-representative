"""app/response/chips.py — suggested follow-up prompts built from the conversation (pure Python).

Chips come from what was just discussed (the products shown, the category, the reply type), never
from a fixed list, and only offer things the assistant can answer from its data. Order tracking and
other general actions appear only when the conversation is about orders.
"""

from typing import Any

from app.schemas.chat import ChatResponseBody
from app.schemas.query import QueryUnderstanding

MAX_CHIPS = 3
MAX_NAME = 45          # product names longer than this are not put into a chip

_ORDER_WORDS = ("order", "track", "refund", "cancel", "return", "replace", "shipping", "delivery", "warranty", "payment")

# Related support questions, offered only after a support conversation (key = word in the topic).
_SUPPORT_FOLLOW_UPS = {
    "track": "What is your return and replacement policy?",
    "cancel": "How long does a refund take?",
    "refund": "How do I track my order?",
    "return": "How long does a refund take?",
}


def _a(word: str) -> str:
    return "an" if word[:1].lower() in "aeiou" else "a"


def _names(response: ChatResponseBody, state: dict[str, Any]) -> list[str]:
    """Products to talk about: in-stock tray cards first, else the compared/discussed products."""
    tray = response.product_tray
    names = [c.name for c in tray if c.availability == "in_stock"] or [c.name for c in tray]
    if not names:
        result = state.get("specialist_result")
        products = sorted(result.data.get("products", []) if result else [],
                          key=lambda p: p["availability"] == "out_of_stock")   # in stock first
        names = [p["name"] for p in products]
    return [n for n in names if len(n) <= MAX_NAME]


def build_chips(response: ChatResponseBody, state: dict[str, Any]) -> list[str]:
    query: QueryUnderstanding | None = state.get("query")
    if query is None or response.type not in ("recommendation", "comparison", "knowledge", "support"):
        return []
    category = (query.entities.category or "").replace("_", " ").strip()   # 'beard_growth_oil' -> 'beard growth oil'
    names = _names(response, state)
    asked_one = state["specialist_result"].data.get("single_pick") if state.get("specialist_result") else False
    chips: list[str] = []

    if response.type == "recommendation":
        if len(names) >= 2:
            chips.append(f"Compare {names[0]} and {names[1]}")
        if len(names) >= 2 and not asked_one:
            chips.append("Which one would you pick for me?")
        if names:
            chips.append(f"Tell me more about {names[0]}")
        if "trimmer" in category.lower() and names:
            chips.append(f"How long does the {names[0]} run on a full charge?")
    elif response.type == "comparison":
        chips.append("Which one would you pick for me?")
        if names:
            chips.append(f"Tell me more about {names[0]}")
        if category:
            chips.append(f"Show me more {category} options")
    elif response.type == "knowledge":
        if category:
            chips.append(f"Suggest {_a(category)} {category}")
        if names:
            chips.append(f"Tell me more about {names[0]}")
    else:  # support
        topic = " ".join(query.entities.attributes).lower() + " " + state.get("message", "").lower()
        if any(w in topic for w in _ORDER_WORDS):
            chips += [v for k, v in _SUPPORT_FOLLOW_UPS.items() if k in topic]
        elif names:
            chips.append(f"Tell me more about {names[0]}")

    last = state.get("message", "").strip().lower()
    unique: list[str] = []
    for chip in chips:
        if chip.lower() != last and chip not in unique:
            unique.append(chip)
    return unique[:MAX_CHIPS]
