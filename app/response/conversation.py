"""app/response/conversation.py — guardrails for conversation replies (pure logic).

The conversation node lets the model write a short, friendly reply. It may not
state facts, so Python checks the text and falls back to fixed lines in the
same voice when anything looks wrong (or the model is unavailable).
"""

import re

_AMOUNT = re.compile(r"(?:₹|\bRs\.?|\bINR)\s?\d|\d\s?(?:rupees|rs\b)", re.IGNORECASE)
_URL = re.compile(r"https?://|www\.", re.IGNORECASE)
_EMAIL = re.compile(r"[^\s@]+@[^\s@]+\.[^\s@]+")
_MARKUP = re.compile(r"(?m)^\s*(?:[-*•]\s|\d+[.)]\s|#{1,6}\s)|<[a-z/][^>]*>|\*\*")
_EMOJI = re.compile("[\U0001F300-\U0001FAFF☀-➿️‍]")
_SPACE = re.compile(r"\s+")

_INJECTION = re.compile(
    r"ignore\s+(?:all\s+|any\s+|your\s+|the\s+)?(?:previous|prior|above|earlier)?\s*(?:instructions|rules|prompt)"
    r"|system\s+prompt|your\s+instructions|pretend\s+(?:to\s+be|you\s*(?:are|'re))|you\s+are\s+now|\bact\s+as\b"
    r"|talk\s+like|speak\s+like|reply\s+as|respond\s+as|role-?play|from\s+now\s+on|\bjailbreak\b",
    re.IGNORECASE,
)

MAX_CHARS = 450

CHAT_FALLBACKS = [
    "Hey, good to see you! Tell me what you're after, whether it's a razor, a trimmer or some beard care.",
    "Happy to help. What are you looking for today: products, grooming tips or an order?",
    "Hi there. I can suggest products, compare them or help with an order, so what do you need?",
]
OFF_TOPIC_FALLBACKS = [
    "That one is outside what I can help with, since I stick to Bombay Shaving Company products and grooming. "
    "Want me to suggest something, compare two products or help with an order?",
    "I can't help with that topic, but I'm happy to help with grooming. Shall I suggest a product, "
    "share a grooming tip or look into an order for you?",
]


def looks_like_injection(message: str) -> bool:
    """A message trying to change the assistant's role, voice or rules.

    The model usually declines these, but small models can slip ("Arr matey...").
    Messages that reach the conversation node are small talk or off-topic, so a
    fixed, safe line is always an acceptable answer for them.
    """
    return bool(_INJECTION.search(message or ""))


def tidy(text: str) -> str:
    """Plain single-paragraph text: no emoji, and at most one exclamation mark."""
    text = _SPACE.sub(" ", _EMOJI.sub("", text or "")).strip()
    first = text.find("!")
    if first == -1:
        return text
    return text[: first + 1] + text[first + 1:].replace("!", ".")


def problems(text: str) -> list[str]:
    """Why a reply may not be sent as it is (empty list = fine)."""
    found = []
    if not text:
        found.append("empty")
    if len(text) > MAX_CHARS:
        found.append("too long")
    if _AMOUNT.search(text):
        found.append("states a price")
    if _URL.search(text):
        found.append("contains a link")
    if _EMAIL.search(text):
        found.append("contains an email address")
    if _MARKUP.search(text):
        found.append("contains list/heading/markup")
    return found


def fallback_reply(off_topic: bool, seed: str) -> str:
    """A fixed line in the same voice, chosen deterministically from `seed`."""
    pool = OFF_TOPIC_FALLBACKS if off_topic else CHAT_FALLBACKS
    return pool[sum(ord(c) for c in seed) % len(pool)]
