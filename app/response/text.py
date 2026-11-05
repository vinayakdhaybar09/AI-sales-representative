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


_EMOJI = re.compile("[\U0001F300-\U0001FAFF\u2600-\u27BF\uFE0F\u200d]")
_NUMBERING = re.compile(r"^\s*\(?\d+[.)]\s*")


def strip_emoji(text: str) -> str:
    return _EMOJI.sub("", text)


def clean_display(text: Any, limit: int) -> str:
    """`clean_text` plus emoji removed (for product copy shown on a page)."""
    return re.sub(r"\s+", " ", strip_emoji(clean_text(text, limit))).strip()


def clean_paragraphs(text: Any, limit: int) -> str:
    """Display text that keeps its paragraph breaks ("\\n\\n" between paragraphs); markup and emoji removed."""
    if not isinstance(text, str):
        return ""
    parts = [clean_display(part, limit) for part in re.split(r"\n\s*\n|\r\n\s*\r\n", text)]
    parts = [p for part in parts for p in ([part] if "\n" not in part else part.splitlines()) if p]
    out, used = [], 0
    for part in parts:
        if used + len(part) > limit:
            break
        out.append(part)
        used += len(part)
    return "\n\n".join(out)


def clean_steps(items: Any, limit_items: int, limit_chars: int) -> list[str]:
    """Usage steps without their own "1)" / "2." numbering (the page numbers them)."""
    return [_NUMBERING.sub("", step) for step in clean_list(items, limit_items, limit_chars)]
