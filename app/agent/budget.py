"""app/agent/budget.py — read a budget out of free text ("under 1500", "2k tak", "around ₹1,000"). Plain Python."""

import re

_PATTERN = re.compile(
    r"(?P<kw>under|below|within|upto|up to|max(?:imum)?|budget(?: is| of)?|around|about|approx(?:imately)?)?\s*"
    r"(?:rs\.?|₹)?\s*(?P<num>\d[\d,]*(?:\.\d+)?)\s*(?P<k>k\b)?\s*(?P<tail>tak|rupees|rs\b|max\b)?", re.I)


def parse_budget(text: str) -> tuple[float, bool] | None:
    """(amount, approximate) for the last budget-like amount in `text`, or None.

    A bare number counts only with a budget word, a ₹/rs sign, a 'k' suffix or 'tak', so "3 days" or "50 employees"
    are not budgets. 'around/about' marks the amount as approximate (a small overshoot is fine).
    """
    found: tuple[float, bool] | None = None
    for m in _PATTERN.finditer(text or ""):
        raw = m.group(0).lower()
        has_signal = bool(m.group("kw") or m.group("k") or m.group("tail") or "₹" in raw or "rs" in raw)
        if not has_signal:
            continue
        value = float(m.group("num").replace(",", "")) * (1000 if m.group("k") else 1)
        if value < 50:           # "under 5 minutes", sizes, counts
            continue
        found = (value, (m.group("kw") or "").lower() in ("around", "about", "approx", "approximately"))
    return found
