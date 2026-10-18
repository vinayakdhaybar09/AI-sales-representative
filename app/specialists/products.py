"""app/specialists/products.py — helpers shared by the specialists (pure logic)."""

import re
from decimal import Decimal
from typing import Any


def to_record(row: dict[str, Any]) -> dict[str, Any]:
    """A products row as a JSON-friendly full record (Decimal -> float)."""
    return {k: (float(v) if isinstance(v, Decimal) else v) for k, v in row.items()}


def _tokens(text: str) -> set[str]:
    """Lowercase word tokens with a crude plural strip ('razors' -> 'razor')."""
    words = re.findall(r"[a-z0-9]+", text.lower())
    return {w[:-1] if len(w) > 3 and w.endswith("s") else w for w in words}


def category_matches(term: str, row: dict[str, Any], meta: dict[str, Any]) -> bool:
    """Does the user's category word describe this product?

    Canonical and enriched category names differ (docs/DATA.md issue 6), so we
    never compare category strings directly: we look for the term's words in
    the canonical category, the product name and the enriched product_type.
    """
    wanted = _tokens(term)
    if not wanted:
        return False
    haystack = _tokens(
        f"{row.get('category', '')} {row.get('name', '')} {(meta or {}).get('product_type') or ''}"
        .replace("_", " ")
    )
    return wanted <= haystack


def normalize_gender(value: str | None) -> str | None:
    """Map free text to 'men' / 'women' (None if no usable preference)."""
    if not value:
        return None
    v = value.strip().lower()
    if v in {"men", "man", "male", "mens", "men's", "boy", "him"}:
        return "men"
    if v in {"women", "woman", "female", "womens", "women's", "girl", "her"}:
        return "women"
    return None
