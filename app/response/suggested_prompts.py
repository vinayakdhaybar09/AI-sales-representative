"""app/response/suggested_prompts.py — the predefined suggested-prompt list.

Suggested prompts are never freely generated (docs/ARCHITECTURE.md): they come
from this small list so they always lead to something the assistant can answer.
"""

SUGGESTED_PROMPTS = [
    "Suggest a razor for sensitive skin",
    "How do I fix a patchy beard?",
    "Suggest a trimmer for body grooming",
    "Compare two trimmers",
    "Which beard oil is good for dry beard?",
    "How do I track my order?",
    "What is your return and replacement policy?",
    "Suggest a face wash for oily skin",
]

# Used by the fallback response (docs/CONTRACTS.md).
FALLBACK_PROMPTS = ["Suggest a trimmer for body grooming", "Compare two trimmers"]


def pick(n: int, seed: str = "") -> list[str]:
    """n distinct prompts, chosen deterministically from `seed` so replies vary
    between messages but are stable for the same message."""
    start = sum(ord(c) for c in seed) % len(SUGGESTED_PROMPTS)
    return [SUGGESTED_PROMPTS[(start + i) % len(SUGGESTED_PROMPTS)] for i in range(n)]
