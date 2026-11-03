from functools import lru_cache
from typing import Literal
from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """All configuration for the app, loaded from environment variables / .env."""
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )

    #app
    app_env: str = "development"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"

    # Secrets (optional for now; required by the phase that first uses them)
    mistral_api_key: SecretStr | None = None
    huggingface_api_key: SecretStr | None = None
    database_url: SecretStr | None = None

    # Models
    chat_model: str = "mistral-small-latest"
    embedding_model: str = "mistral-embed"
    embedding_dimensions: int = 1024

    # Conversations and request limits
    conversation_ttl_minutes: float = 15      # idle time before a conversation expires
    request_timeout_seconds: float = 90       # whole-request budget for one chat message (room for a review + one revision)
    reviewer_enabled: bool = True             # LLM check that the reply fulfils the request
    reviewer_timeout_seconds: float = 15
    composer_temperature: float = 0.3         # a little variety in wording; extraction and review stay at 0
    conversation_timeout_seconds: float = 15   # greeting / off-topic reply (falls back to fixed lines)

@lru_cache
def get_settings() -> Settings:
    return Settings()