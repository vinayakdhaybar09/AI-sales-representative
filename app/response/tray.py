"""app/response/tray.py — the product tray, built in Python from specialist output.

The Composer LLM never writes tray fields. Only the recommendation specialist
produces a tray, and it can only contain products that specialist returned.
"""

from app.schemas.chat import ProductCard
from app.schemas.specialist import SpecialistOutput


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
        )
        for p in result.data.get("products", [])
    ]
