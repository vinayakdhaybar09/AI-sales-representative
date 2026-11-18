"""app/agent/profile_extract.py — a deterministic safety net for the customer profile.

The model is asked to call `remember` when a shopper states a fact about themselves, but it often skips the call.
This reads the same few facts straight from the shopper's message with plain patterns (no LLM), so the profile
(and the "I remember" chips in the UI) fills in reliably. It is deliberately conservative: when unsure, it saves
nothing. Anything the model saved itself wins over this (see runner.py).
"""

import re

_NEG_RX = re.compile(r"\b(?:not|no|never|don'?t have|dont have|nahi)\s+(?:\w+\s+){0,2}$", re.I)
_SKIN = r"oily|dry|sensitive|combination|normal|acne[- ]prone"
_HAIR = r"curly|straight|wavy|thick|thin|coarse|fine"
_FOR = {
    "dad": "dad", "father": "dad", "papa": "dad", "brother": "brother", "bhai": "brother", "husband": "husband",
    "boyfriend": "boyfriend", "friend": "friend", "son": "son", "wife": "wife", "girlfriend": "girlfriend",
    "mom": "mom", "mother": "mom", "mummy": "mom", "sister": "sister", "boss": "boss", "colleague": "colleague",
}

_SKIN_RX = [
    re.compile(rf"\b({_SKIN})\s+skin\b", re.I),
    re.compile(rf"\bskin\s+(?:is|type is|type:)?\s*({_SKIN})\b", re.I),
]
_HAIR_RX = re.compile(rf"\b({_HAIR})\s+(?:beard|hair)\b", re.I)
_BUDGET_RX = [
    re.compile(r"\b(?:under|below|within|upto|up to|max(?:imum)?|less than|budget(?:\s+is|\s+of|:)?|around|about)\s*(?:rs\.?|inr|₹)?\s*([\d,]+(?:\.\d+)?)\s*(k)?\b", re.I),
    re.compile(r"(?:₹|rs\.?|inr)\s*([\d,]+(?:\.\d+)?)\s*(k)?\s*(?:budget|max|tak|se kam)", re.I),
    re.compile(r"\b([\d,]+)\s*(k)?\s*(?:rupees|rs|₹)?\s*(?:tak|se kam|ke andar)\b", re.I),
]
_FOR_RX = re.compile(r"\bfor\s+(?:my|mere|meri)\s+(" + "|".join(_FOR) + r")\b", re.I)
_SELF_RX = re.compile(r"\bfor\s+(?:myself|me)\b|\bfor my own use\b|\bmere liye\b", re.I)


def _amount(raw: str, k: str | None) -> int | None:
    try:
        value = float(raw.replace(",", ""))
    except ValueError:
        return None
    if k:
        value *= 1000
    value = int(value)
    return value if 50 <= value <= 50000 else None


def extract_profile(message: str) -> dict:
    """Facts stated in this one message: skin_type, hair_type, budget_max, for_whom. Empty when nothing is clear."""
    found: dict = {}
    text = message.strip()

    for rx in _SKIN_RX:
        m = rx.search(text)
        if m and not _NEG_RX.search(text[max(0, m.start() - 30):m.start()]):
            found["skin_type"] = m.group(1).lower().replace(" ", "-")
            break

    m = _HAIR_RX.search(text)
    if m:
        found["hair_type"] = m.group(1).lower()

    for rx in _BUDGET_RX:
        m = rx.search(text)
        if m:
            amount = _amount(m.group(1), m.group(2) if m.lastindex and m.lastindex >= 2 else None)
            if amount:
                found["budget_max"] = amount
                break

    m = _FOR_RX.search(text)
    if m:
        found["for_whom"] = _FOR[m.group(1).lower()]
    elif _SELF_RX.search(text):
        found["for_whom"] = "myself"
    return found
