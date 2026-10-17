"""app/db/connection.py — async connection pool.

Design notes
------------
- Uses psycopg v3 async pool (AsyncConnectionPool) from psycopg_pool.
- The pool is opened inside the FastAPI lifespan, not at module import time,
  so a missing DATABASE_URL is only fatal at first DB use, not at startup.
- Callers obtain a connection with: async with get_pool().connection() as conn
- pgvector's type adapters are registered on every new connection via a
  configure callback, so vector columns are automatically handled.

Secrets rule: DATABASE_URL is a SecretStr; .get_secret_value() is called
exactly once here, inside open_pool().
"""

import logging

import psycopg
from psycopg_pool import AsyncConnectionPool
from pgvector.psycopg import register_vector_async

from app.core.config import get_settings

logger = logging.getLogger(__name__)

# Module-level singleton; set by open_pool(), cleared by close_pool().
_pool: AsyncConnectionPool | None = None


async def _configure_conn(conn: psycopg.AsyncConnection) -> None:
    """Register pgvector type adapters on each new pooled connection."""
    await register_vector_async(conn)


async def open_pool() -> None:
    """Create and open the async connection pool.

    Called once from the FastAPI lifespan on startup.
    Raises RuntimeError if DATABASE_URL is not configured.
    """
    global _pool

    settings = get_settings()
    if not settings.database_url:
        # Defer error to first use, not startup — but warn loudly here.
        logger.warning(
            "DATABASE_URL is not set; DB operations will fail at first use"
        )
        return

    conninfo = settings.database_url.get_secret_value()
    logger.info("Opening async connection pool")
    _pool = AsyncConnectionPool(
        conninfo=conninfo,
        min_size=1,
        max_size=10,
        configure=_configure_conn,
        # Do NOT pass open=True here (deprecated in psycopg-pool 3.x).
        # open() is called explicitly below.
        open=False,
    )
    await _pool.open()
    logger.info("Connection pool open")


async def close_pool() -> None:
    """Close the pool gracefully on shutdown."""
    global _pool
    if _pool is not None:
        logger.info("Closing connection pool")
        await _pool.close()
        _pool = None


def get_pool() -> AsyncConnectionPool:
    """Return the active pool.

    Raises RuntimeError if open_pool() was not called or DATABASE_URL was
    missing — this is the intended 'fail at first DB use' behaviour.
    """
    if _pool is None:
        raise RuntimeError(
            "Database pool is not initialised. "
            "Ensure DATABASE_URL is set and the server has started up correctly."
        )
    return _pool
