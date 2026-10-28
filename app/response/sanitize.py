"""app/response/sanitize.py — remove stray HTML/CSS from a composed reply (pure Python).

The data copied from the website sometimes carries markup, and models occasionally echo it (a `<br>` in a
table cell, an HTML comment). The app renders Markdown only, so such markup shows up as literal text.
Cleaning it is safer than rejecting an otherwise good reply; the validator still rejects what is left.
"""

import re

_BLOCK = re.compile(r"<\s*(style|script)\b.*?<\s*/\s*\1\s*>", re.IGNORECASE | re.DOTALL)
_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)
_BREAK = re.compile(r"<\s*br\s*/?\s*>", re.IGNORECASE)
_TAG = re.compile(r"<\s*/?\s*(?:style|script|td|tr|table|div|span|p)\b[^>]*>", re.IGNORECASE)
_TRAILING = re.compile(r"[ \t]+\n")
_BLANKS = re.compile(r"\n{3,}")


def sanitize_markdown(markdown: str) -> str:
    text = _BLOCK.sub(" ", markdown)
    text = _COMMENT.sub(" ", text)
    text = _BREAK.sub(" ", text)
    text = _TAG.sub("", text)
    text = text.replace("-->", "").replace("<!--", "")
    return _BLANKS.sub("\n\n", _TRAILING.sub("\n", text)).strip()
