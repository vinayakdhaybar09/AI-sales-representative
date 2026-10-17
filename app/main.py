import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from app.api.routes import chat, health
from app.core.config import get_settings
from app.core.logging import setup_logging

setup_logging()
logger = logging.getLogger(__name__)



@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    logger.info(
        "Starting up (env=%s, chat_model=%s, embedding_model=%s)",
        settings.app_env,
        settings.chat_model,
        settings.embedding_model,
    )
    yield
    logger.info("Shutting down")


app = FastAPI(
    title="BSC AI Sales Representative",
    version="0.3.0",
    lifespan=lifespan
)

app.include_router(health.router)
app.include_router(chat.router)