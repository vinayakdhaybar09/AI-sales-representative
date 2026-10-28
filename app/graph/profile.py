"""app/graph/profile.py — what we know about the customer, carried across turns (pure Python).

Query Understanding reads one message at a time, so a short follow-up such as
"something under ₹200" or "recommend one" arrives without its category, budget or
skin type. The profile keeps those details and fills the gaps in the next turn.

Rules (docs/DECISIONS.md: business logic lives in Python):
- Customer traits (skin type, hair type, who it is for) persist for the whole conversation.
- A budget belongs to the topic it was given for; it is only carried to a follow-up on the same category.
- A category is only carried to a message that adds constraints and names no other subject.
"""

import re
from typing import Any

from app.schemas.query import QueryUnderstanding
from app.specialists.products import normalize_gender

MAX_ITEMS = 4   # per list, newest kept


_WOMEN = re.compile(
    r"\b(?:wife|girlfriend|fiancee|mother|mom|mum|sister|daughter|aunt|grandmother|she|her|hers|woman|women|"
    r"womens|women's|lady|ladies|female|girl|girls|bikini)\b", re.IGNORECASE)
_MEN = re.compile(
    r"\b(?:husband|boyfriend|fiance|father|dad|brother|son|uncle|grandfather|he|him|his|man|men|mens|men's|"
    r"male|boy|boys|guy|beard)\b", re.IGNORECASE)


def detect_audience(text: str) -> str | None:
    """'women' or 'men' when the words name who the products are for; None when they don't.

    The model's own guess is not trusted for this (a small model answers 'men' for 'for myself').
    Only one side may match: 'a gift for my wife and my brother' names no single audience.
    """
    women, men = bool(_WOMEN.search(text)), bool(_MEN.search(text))
    if women == men:
        return None
    return "women" if women else "men"


def _union(old: list[str], new: list[str]) -> list[str]:
    merged = list(old)
    merged += [x for x in new if x not in merged]
    return merged[-MAX_ITEMS:]


def _same(a: str | None, b: str | None) -> bool:
    return (a or "").strip().lower() == (b or "").strip().lower()


def apply_profile(query: QueryUnderstanding, profile: dict[str, Any]) -> None:
    """Fill what this message left out from the profile (changes `query` in place)."""
    if not profile or query.intent != "recommendation":
        return
    e, f = query.entities, query.filters

    adds_constraints_only = not (e.products or e.use_case or e.body_area or e.attributes)
    if not e.category and adds_constraints_only and profile.get("category"):
        e.category = profile["category"]

    if f.budget_max is None and f.budget_min is None and _same(e.category, profile.get("category")):
        f.budget_max = profile.get("budget_max")
        f.budget_min = profile.get("budget_min")

    if not f.skin_type:
        f.skin_type = list(profile.get("skin_type", []))
    if not f.hair_type:
        f.hair_type = list(profile.get("hair_type", []))
    if not normalize_gender(f.gender) and profile.get("audience"):
        f.gender = profile["audience"]


def update_profile(profile: dict[str, Any], query: QueryUnderstanding) -> dict[str, Any]:
    """The profile after this turn: new details override or extend the old ones."""
    new = dict(profile or {})
    e, f = query.entities, query.filters

    if e.category:
        new["category"] = e.category
    if f.budget_max is not None or f.budget_min is not None:
        new["budget_max"], new["budget_min"] = f.budget_max, f.budget_min
    for key, values in (("skin_type", f.skin_type), ("hair_type", f.hair_type), ("use_case", e.use_case)):
        if values:
            new[key] = _union(new.get(key, []), values)
    audience = normalize_gender(f.gender)
    if audience:
        new["audience"] = audience
    if e.products:
        new["focus_products"] = e.products[-MAX_ITEMS:]
    return {k: v for k, v in new.items() if v not in (None, [], "")}


def describe(profile: dict[str, Any]) -> str:
    """One line for the Composer prompt ('' when nothing is known)."""
    if not profile:
        return ""
    parts = []
    if profile.get("category"):
        parts.append(f"looking for: {profile['category'].replace('_', ' ')}")
    if profile.get("budget_max") is not None:
        parts.append(f"budget up to ₹{profile['budget_max']:g}")
    if profile.get("budget_min") is not None:
        parts.append(f"budget from ₹{profile['budget_min']:g}")
    for key, label in (("skin_type", "skin"), ("hair_type", "hair"), ("use_case", "use")):
        if profile.get(key):
            parts.append(f"{label}: {', '.join(profile[key])}")
    if profile.get("audience"):
        parts.append(f"shopping for: {profile['audience']}")
    if profile.get("focus_products"):
        parts.append(f"discussing: {', '.join(profile['focus_products'])}")
    return "; ".join(parts)
