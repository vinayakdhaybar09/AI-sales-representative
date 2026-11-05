"""app/response/product_detail.py — a `products` row -> the cleaned ProductDetail (pure logic).

Price, availability, URL and images come from the row (the single source of
truth); long texts are cleaned for display only (stray HTML/CSS and emoji
removed, the database is untouched).
"""

from typing import Any

from app.response.text import clean_display, clean_list, clean_paragraphs, clean_steps
from app.schemas.product import FaqItem, InfoSection, ProductDetail

MAX_IMAGES = 12


def _images(row: dict[str, Any], details: dict[str, Any]) -> list[str]:
    """All image URLs, de-duplicated, main image first."""
    urls = [row.get("image_url"), *(details.get("images") or [])]
    seen: list[str] = []
    for url in urls:
        if isinstance(url, str) and url.startswith("http") and url not in seen:
            seen.append(url)
    return seen[:MAX_IMAGES]


def _sections(info: dict[str, Any]) -> list[InfoSection]:
    """Extra free-text sections ("product information", ...) with readable titles."""
    other = info.get("other_information")
    if not isinstance(other, dict):
        return []
    sections = []
    for key, value in other.items():
        text = clean_paragraphs(value, 1200)
        if text:
            sections.append(InfoSection(title=str(key).replace("_", " ").strip().capitalize(), text=text))
    return sections[:4]


def _faqs(info: dict[str, Any]) -> list[FaqItem]:
    faqs = []
    for item in info.get("faqs") or []:
        if isinstance(item, dict):
            q, a = clean_display(item.get("question"), 200), clean_display(item.get("answer"), 600)
            if q and a:
                faqs.append(FaqItem(question=q, answer=a))
    return faqs[:5]


def build_product_detail(row: dict[str, Any]) -> ProductDetail:
    details = row.get("details") or {}
    info = details.get("detailed_information") or {}
    if not isinstance(info, dict):
        info = {}
    specs = details.get("specifications") or {}

    price = float(row["price"])
    original = float(row.get("original_price") or 0)
    reviews = int(row.get("review_count") or 0)
    rating = float(row.get("rating") or 0)
    has_reviews = reviews > 0 and rating > 0

    description = clean_paragraphs(row.get("description"), 1500)
    about = clean_paragraphs(info.get("about_the_product"), 2500)
    if about and about.replace("\n\n", " ") == description.replace("\n\n", " "):
        about = ""   # the same text twice adds nothing
    features = clean_list(info.get("key_features"), 8, 160) or clean_list(details.get("features"), 8, 160)
    weight = specs.get("weight_grams") if isinstance(specs, dict) else None

    return ProductDetail(
        product_id=str(row["id"]),
        name=row["name"],
        category=row.get("category"),
        price=price,
        original_price=original if original > price else None,
        rating=rating if has_reviews else None,
        review_count=reviews if has_reviews else None,
        availability=row["availability"],
        product_url=row.get("url") or "",
        images=_images(row, details),
        description=description or None,
        about=about or None,
        key_features=features,
        how_to_use=clean_steps(info.get("how_to_use"), 8, 220),
        other_information=_sections(info),
        faqs=_faqs(info),
        weight_grams=float(weight) if isinstance(weight, (int, float)) and weight > 0 else None,
    )
