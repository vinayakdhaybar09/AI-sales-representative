import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from app.api.error_handlers import register_error_handlers
from app.api.routes import admin, chat, events, health, products, queries
from app.core.config import get_settings
from app.core.logging import setup_logging
from app.db.connection import open_pool, close_pool

setup_logging()
logger = logging.getLogger(__name__)


async def _warm_up() -> None:
    """Load the catalog cache and the embedding client before the first customer arrives."""
    try:
        from app.agent import retrieval
        from app.db.connection import get_pool
        from app.llm.models import get_embeddings
        async with get_pool().connection() as conn:
            await retrieval.catalog(conn)
        await get_embeddings().aembed_query("warm up")
    except Exception as exc:
        logger.warning("Warm-up skipped: %s", type(exc).__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    logger.info(
        "Starting up (env=%s, chat_model=%s, embedding_model=%s)",
        settings.app_env,
        settings.chat_model,
        settings.embedding_model,
    )
    await open_pool()
    asyncio.create_task(_warm_up())
    yield
    await close_pool()
    logger.info("Shutting down")


app = FastAPI(
    title="BSC AI Sales Representative",
    version="0.5.0",
    lifespan=lifespan
)

register_error_handlers(app)
app.include_router(health.router)
app.include_router(chat.router)
app.include_router(products.router)
app.include_router(queries.router)
app.include_router(events.router)
app.include_router(admin.router)

# Dev-only vector search; never exposed outside development.
if get_settings().app_env == "development":
    from app.api.routes import dev

    app.include_router(dev.router)
