import logging

from app.core.errors import not_found
from app.db.connection import get_pool
from app.db.repositories.products import get_product_by_id
from app.response.product_detail import build_product_detail
from app.schemas.product import ProductDetail

logger = logging.getLogger(__name__)


async def get_product_detail(product_id: str) -> ProductDetail:
    """One product, cleaned for display. Raises a client-safe `not_found` when the id is unknown."""
    async with get_pool().connection() as conn:
        row = await get_product_by_id(conn, product_id)
    if row is None:
        logger.info("Product detail not found (product_id=%s)", product_id)
        raise not_found("We couldn't find that product.")
    return build_product_detail(row)
