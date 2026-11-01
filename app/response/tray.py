"""app/response/tray.py — the product tray, built in Python from specialist output.

The Composer LLM never writes tray fields. Only the recommendation and
product_finalization specialists produce a tray, and it can only contain
products that specialist returned.
"""

from typing import Any

from app.response.text import clean_list, clean_text
from app.schemas.chat import ProductCard
from app.schemas.specialist import SpecialistOutput


def card_extras(product: dict[str, Any]) -> dict[str, Any]:
    """Optional card fields derived from a products row.

    A 0.0 rating means "no reviews yet" (docs/DATA.md issue 7), so it is sent
    as null, never as a rating. original_price only appears for a real discount.
    """
    reviews = int(product.get("review_count") or 0)
    rating = float(product.get("rating") or 0)
    price = float(product["price"])
    original = float(product.get("original_price") or 0)
    return {
        "rating": rating if reviews > 0 and rating > 0 else None,
        "review_count": reviews if reviews > 0 and rating > 0 else None,
        "original_price": original if original > price else None,
    }


TRAY_SPECIALISTS = ("recommendation", "product_finalization")


def featured_extras(product: dict[str, Any]) -> dict[str, Any]:
    """Extra fields for the large product_finalization card (all may be empty).

    Benefits fall back to the product's feature list when it has no benefits.
    Text is cleaned of stray HTML/CSS for display; the database is untouched.
    """
    details = product.get("details") or {}
    info = details.get("detailed_information") or {}
    benefits = clean_list(info.get("benefits"), 5, 160) if isinstance(info, dict) else []
    usage = clean_list(info.get("how_to_use"), 6, 200) if isinstance(info, dict) else []
    return {
        "rank": product.get("rank"),
        "description": clean_text(product.get("description"), 500) or None,
        "key_benefits": benefits or clean_list(details.get("features"), 5, 160),
        "how_to_use": usage,
        "selection_reasons": list(product.get("selection_reasons") or []),
    }


def build_tray(result: SpecialistOutput) -> list[ProductCard]:
    """One card per product, in specialist order; [] for every other intent."""
    if result.specialist not in TRAY_SPECIALISTS or result.status != "success":
        return []
    featured = result.specialist == "product_finalization"
    return [
        ProductCard(
            product_id=str(p["id"]),
            name=p["name"],
            price=float(p["price"]),
            image_url=p.get("image_url") or "",
            product_url=p.get("url") or "",
            availability=p["availability"],
            **card_extras(p),
            **(featured_extras(p) if featured else {}),
        )
        for p in result.data.get("products", [])
    ]
