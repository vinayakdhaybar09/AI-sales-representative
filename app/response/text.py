"""app/response/text.py — turn raw product text into display text (pure logic).

Some descriptions contain stray HTML/CSS comments (docs/DATA.md issue 8). The
database keeps them as they are; text shown to a customer is cleaned here.
"""

import re
from typing import Any

_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)
_TAG = re.compile(r"<[^>]+>")
_SPACE = re.compile(r"\s+")


def clean_text(text: Any, limit: int) -> str:
    """Strip stray HTML/CSS comments and tags, collapse whitespace, cap length."""
    s = _SPACE.sub(" ", _TAG.sub(" ", _COMMENT.sub(" ", str(text or "")))).strip()
    return s if len(s) <= limit else s[:limit].rsplit(" ", 1)[0] + "…"


def clean_list(items: Any, limit_items: int, limit_chars: int) -> list[str]:
    """A list (or a single string) of texts, cleaned, empty ones dropped, capped."""
    if isinstance(items, str):
        items = [items]
    if not isinstance(items, list):
        return []
    cleaned = (clean_text(i, limit_chars) for i in items if isinstance(i, str))
    return [c for c in cleaned if c][:limit_items]
