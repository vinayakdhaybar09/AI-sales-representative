from fastapi import APIRouter, Path

from app.schemas.product import ProductDetailEnvelope
from app.services.product_service import get_product_detail

router = APIRouter(prefix="/api", tags=["products"])


@router.get("/products/{product_id}", response_model=ProductDetailEnvelope)
async def product_detail(product_id: str = Path(pattern=r"^\d{1,30}$")) -> ProductDetailEnvelope:
    """Full product data for the preview panel (images, features, how to use, FAQs)."""
    return ProductDetailEnvelope(product=await get_product_detail(product_id))
