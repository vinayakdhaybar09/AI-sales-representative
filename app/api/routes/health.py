"""Health check route.

GET /health always returns HTTP 200 so load balancers keep the pod alive.
The 'db' field tells operators whether the database is reachable:
  - "ok"             — pool exists and a lightweight query succeeded
  - "not_configured" — DATABASE_URL is not set (dev/test without a DB)
  - "unavailable"    — pool exists but the ping query failed
"""

import logging

from fastapi import APIRouter

from app.db.connection import get_pool

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/health")
async def health_check() -> dict:
    db_status = await _db_ping()
    return {"status": "ok", "service": "bsc-backend", "db": db_status}


async def _db_ping() -> str:
    """Try a cheap SELECT 1 against the pool. Never raises."""
    try:
        pool = get_pool()
    except RuntimeError:
        # Pool not initialised — DATABASE_URL was missing at startup.
        return "not_configured"

    try:
        async with pool.connection() as conn:
            await conn.execute("SELECT 1")
        return "ok"
    except Exception as exc:
        logger.warning("DB health ping failed: %s", exc)
        return "unavailable"
