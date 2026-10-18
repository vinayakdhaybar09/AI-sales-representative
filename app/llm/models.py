"""app/llm/models.py — the only place that builds LLM / embedding models.

Secrets rule: the Mistral key stays a SecretStr. langchain-mistralai accepts a
SecretStr for `api_key`, so the raw value is never unwrapped in our code.
"""

import logging
from functools import lru_cache

from langchain_mistralai import ChatMistralAI, MistralAIEmbeddings

from app.core.config import get_settings

logger = logging.getLogger(__name__)


class MissingApiKeyError(RuntimeError):
    """Raised at first model use (not at startup) when a key is not configured."""


@lru_cache
def get_embeddings() -> MistralAIEmbeddings:
    """Return the shared Mistral embedding client.

    Cached because constructing it loads a tokenizer (used only to size
    batches). Retries on 429/5xx are handled by the client itself
    (max_retries attempts, wait_time seconds apart).
    """
    settings = get_settings()
    if settings.mistral_api_key is None:
        raise MissingApiKeyError(
            "MISTRAL_API_KEY is not set. Add it to .env and restart."
        )
    logger.info("Building embeddings client (model=%s)", settings.embedding_model)
    return MistralAIEmbeddings(
        model=settings.embedding_model,
        api_key=settings.mistral_api_key,
        max_retries=5,
        wait_time=20,
        timeout=60,
        max_concurrent_requests=2,
    )


@lru_cache
def get_chat_model() -> ChatMistralAI:
    """Return the shared Mistral chat model (temperature 0: we extract, not create)."""
    settings = get_settings()
    if settings.mistral_api_key is None:
        raise MissingApiKeyError(
            "MISTRAL_API_KEY is not set. Add it to .env and restart."
        )
    logger.info("Building chat model (model=%s)", settings.chat_model)
    return ChatMistralAI(
        model=settings.chat_model,
        api_key=settings.mistral_api_key,
        temperature=0,
        max_retries=2,
        timeout=60,
    )
