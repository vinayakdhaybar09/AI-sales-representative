"""app/graph/preferences.py — the customer's structured memory (pure Python).

Raw chat history only keeps the last few messages, so a need mentioned early
("sensitive skin") would be forgotten. Instead, after every in-scope turn we
merge what Query Understanding extracted into one small `preferences` dict.
No LLM call is involved. See docs/CONTRACTS.md → Conversation state.
"""

from typing import Any

from app.schemas.query import QueryUnderstanding

MAX_LIST_ITEMS = 8

# Facts about the person: they survive a change of product category.
PERSONAL_LISTS = ("skin_type", "hair_type")
PERSONAL_SCALARS = ("gender",)
# Facts about the current need: "under ₹2000" for a trimmer must not leak into a face wash search.
NEED_LISTS = ("use_case", "body_area", "required_features", "exclusions")
NEED_SCALARS = ("budget_min", "budget_max")
LIST_FIELDS = PERSONAL_LISTS + NEED_LISTS
SCALAR_FIELDS = PERSONAL_SCALARS + NEED_SCALARS


def extract(query: QueryUnderstanding) -> dict[str, Any]:
    """The non-empty preference-worthy fields of one message."""
    e, f = query.entities, query.filters
    found: dict[str, Any] = {
        "category": (e.category or "").strip().lower() or None,
        "use_case": list(e.use_case),
        "body_area": list(e.body_area),
        "skin_type": list(f.skin_type),
        "hair_type": list(f.hair_type),
        "required_features": list(f.required_features),
        "exclusions": list(f.exclusions),
        "gender": f.gender,
        "budget_min": f.budget_min,
        "budget_max": f.budget_max,
    }
    return {k: v for k, v in found.items() if v not in (None, "", [])}


def merge(stored: dict[str, Any] | None, query: QueryUnderstanding) -> dict[str, Any]:
    """Stored preferences + this message. New single values win; lists are added to."""
    prefs = dict(stored or {})
    new = extract(query)

    old_category = prefs.get("category")
    if new.get("category") and old_category and new["category"] != old_category:
        for key in NEED_LISTS + NEED_SCALARS:     # a different product: start the need afresh
            prefs.pop(key, None)

    for key, value in new.items():
        if key in LIST_FIELDS:
            merged = list(prefs.get(key, []))
            merged += [v for v in value if v.lower() not in {m.lower() for m in merged}]
            prefs[key] = merged[:MAX_LIST_ITEMS]
        else:
            prefs[key] = value
    return prefs


def apply_to_query(query: QueryUnderstanding, prefs: dict[str, Any]) -> QueryUnderstanding:
    """A copy of `query` whose empty fields are filled from `prefs`.

    What the customer says now always wins; memory only fills the gaps.
    """
    q = query.model_copy(deep=True)
    if not q.entities.category and prefs.get("category"):
        q.entities.category = prefs["category"]
    for key in ("use_case", "body_area"):
        if not getattr(q.entities, key) and prefs.get(key):
            setattr(q.entities, key, list(prefs[key]))
    for key in ("skin_type", "hair_type", "required_features", "exclusions"):
        if not getattr(q.filters, key) and prefs.get(key):
            setattr(q.filters, key, list(prefs[key]))
    for key in ("gender", "budget_min", "budget_max"):
        if getattr(q.filters, key) is None and prefs.get(key) is not None:
            setattr(q.filters, key, prefs[key])
    return q
