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
    groq_api_key: SecretStr | None = None

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

    # Salesperson agent (app/agent). Free Groq models first, Mistral (CHAT_MODEL) last.
    # Comma-separated, tried in order; a model that is rate limited is skipped for a while.
    agent_models: str = "openai/gpt-oss-120b,qwen/qwen3.8-27b,openai/gpt-oss-20b"
    agent_max_rounds: int = 4                  # tool-calling rounds per message
    agent_history_messages: int = 10           # past messages sent to the model
    session_ttl_minutes: float = 360           # idle time before a chat session is forgotten

@lru_cache
def get_settings() -> Settings:
    return Settings()