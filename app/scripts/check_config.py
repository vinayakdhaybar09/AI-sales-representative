from app.core.config import get_settings


def is_set(secret) -> bool:
    return bool(secret and secret.get_secret_value())


settings = get_settings()

print(f"APP_ENV              : {settings.app_env}")
print(f"LOG_LEVEL            : {settings.log_level}")
print(f"CHAT_MODEL           : {settings.chat_model}")
print(f"EMBEDDING_MODEL      : {settings.embedding_model}")
print(f"EMBEDDING_DIMENSIONS : {settings.embedding_dimensions}")
print(f"MISTRAL_API_KEY set  : {is_set(settings.mistral_api_key)}")
print(f"HUGGINGFACE_API_KEY  : {is_set(settings.huggingface_api_key)}")
print(f"DATABASE_URL set     : {is_set(settings.database_url)}")
print(f"repr(settings) hides secrets: {settings.mistral_api_key!r}")