"""app/response/comparison_table.py — the comparison table, built in Python from specialist output.

Like the product tray, the Composer LLM never writes it. Every comparison has the
same shape: one column per product (2-3) and these rows, in this order. A row
with no data for any product is dropped; a missing cell is an empty list.
"""

from typing import Any

from app.response.text import clean_display, clean_list
from app.response.tray import card_extras
from app.schemas.chat import ComparisonRow, ComparisonTable, ProductCard
from app.schemas.specialist import MAX_COMPARED_PRODUCTS as MAX_PRODUCTS, SpecialistOutput

DESCRIPTION_CHARS = 200
MAX_BENEFITS = 4
MAX_FEATURES = 5
MAX_SPEC_ROWS = 5
SPEC_VALUE_CHARS = 80


def _card(product: dict[str, Any]) -> ProductCard:
    return ProductCard(
        product_id=str(product["id"]),
        name=product["name"],
        price=float(product["price"]),
        image_url=product.get("image_url") or "",
        product_url=product.get("url") or "",
        availability=product["availability"],
        **card_extras(product),
    )


def _price(card: ProductCard) -> list[str]:
    lines = [f"₹{card.price:g}"]
    if card.original_price:
        save = round((card.original_price - card.price) / card.original_price * 100)
        lines.append(f"was ₹{card.original_price:g} · save {save}%")
    return lines


def _rating(card: ProductCard) -> list[str]:
    if card.rating is None or card.review_count is None:
        return ["No ratings yet"]
    return [f"{card.rating:g}/5", f"{card.review_count} reviews"]


def _details(product: dict[str, Any]) -> dict[str, Any]:
    return product.get("details") or {}


def _benefits(product: dict[str, Any]) -> list[str]:
    info = _details(product).get("detailed_information")
    return clean_list(info.get("benefits"), MAX_BENEFITS, 160) if isinstance(info, dict) else []


def _features(product: dict[str, Any]) -> list[str]:
    return clean_list(_details(product).get("features"), MAX_FEATURES, 160)


# Only specifications a customer cares about. The data also has internal fields (sku, barcode, options) that must never be shown.
SHOWN_SPECS = {"weight_grams": ("Weight", "{} g")}


def _spec_rows(products: list[dict[str, Any]]) -> list[ComparisonRow]:
    """Shown specification rows, only when at least two products have the value (otherwise there is nothing to compare)."""
    rows = []
    for key, (label, template) in SHOWN_SPECS.items():
        cells = []
        for p in products:
            raw = (_details(p).get("specifications") or {}).get(key) if isinstance(_details(p).get("specifications"), dict) else None
            text = clean_display(raw, SPEC_VALUE_CHARS) if raw not in (None, "", 0, "0") else ""
            cells.append([template.format(text)] if text else [])
        if sum(1 for c in cells if c) >= 2:
            rows.append(ComparisonRow(key=f"spec:{key}", label=label, cells=cells))
    return rows[:MAX_SPEC_ROWS]


def build_comparison_table(result: SpecialistOutput) -> ComparisonTable | None:
    """The table for a successful comparison with 2-3 products; None for everything else."""
    if result.specialist != "comparison" or result.status != "success":
        return None
    products = result.data.get("products", [])[:MAX_PRODUCTS]
    if len(products) < 2:
        return None
    cards = [_card(p) for p in products]
    benefits = [_benefits(p) for p in products]
    features = [_features(p) for p in products]
    if features == benefits:                      # the tray-style fallback: do not show the same list twice
        features = [[] for _ in products]

    rows = [
        ComparisonRow(key="price", label="Price", cells=[_price(c) for c in cards]),
        ComparisonRow(key="availability", label="Availability",
                      cells=[["In stock" if c.availability == "in_stock" else "Currently out of stock"] for c in cards]),
        ComparisonRow(key="rating", label="Rating", cells=[_rating(c) for c in cards]),
        ComparisonRow(key="description", label="Description",
                      cells=[[d] if (d := clean_display(p.get("description"), DESCRIPTION_CHARS)) else [] for p in products]),
        ComparisonRow(key="benefits", label="Key benefits", cells=benefits),
        ComparisonRow(key="features", label="Key features", cells=features),
        *_spec_rows(products),
    ]
    rows = [r for r in rows if any(r.cells)]
    return ComparisonTable(products=cards, rows=rows)
