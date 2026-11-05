"""app/schemas/product.py — the product detail shown in the frontend's preview panel (docs/CONTRACTS.md)."""

from pydantic import BaseModel, Field

from app.schemas.chat import Availability


class FaqItem(BaseModel):
    question: str
    answer: str


class InfoSection(BaseModel):
    title: str
    text: str


class ProductDetail(BaseModel):
    """Everything we store about one product, cleaned for display. Any list or text may be empty."""

    product_id: str
    name: str
    category: str | None = None
    price: float
    original_price: float | None = None     # only when higher than price
    rating: float | None = None             # null when there are no reviews
    review_count: int | None = None
    availability: Availability
    product_url: str
    images: list[str] = Field(default_factory=list)   # first = the card image
    description: str | None = None          # paragraphs separated by a blank line
    about: str | None = None                # longer "about the product" text, same format
    key_features: list[str] = Field(default_factory=list)
    how_to_use: list[str] = Field(default_factory=list)
    other_information: list[InfoSection] = Field(default_factory=list)
    faqs: list[FaqItem] = Field(default_factory=list)
    weight_grams: float | None = None


class ProductDetailEnvelope(BaseModel):
    success: bool = True
    product: ProductDetail
    error: None = None
