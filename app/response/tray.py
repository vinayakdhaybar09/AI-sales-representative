"""app/response/tray.py — the product tray, built in Python from specialist output.

The Composer LLM never writes tray fields. Only the recommendation specialist
produces a tray, and it can only contain products that specialist returned.
"""

from typing import Any

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


def build_tray(result: SpecialistOutput) -> list[ProductCard]:
    """One card per recommended product, in specialist order; [] for every other intent."""
    if result.specialist != "recommendation" or result.status != "success":
        return []
    return [
        ProductCard(
            product_id=str(p["id"]),
            name=p["name"],
            price=float(p["price"]),
            image_url=p.get("image_url") or "",
            product_url=p.get("url") or "",
            availability=p["availability"],
            **card_extras(p),
        )
        for p in result.data.get("products", [])
    ]
