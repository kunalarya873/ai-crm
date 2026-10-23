from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "AI CRM API"
    app_version: str = "0.1.0"
    debug: bool = False
    database_url: str = "sqlite+aiosqlite:///./ai_crm_phase1.db"
    api_v1_prefix: str = "/api/v1"
    auth_secret_key: str = "local-development-secret-change-me"
    auth_issuer: str = "ai-crm-api"
    auth_token_ttl_minutes: int = 60
    auto_create_tables: bool = True
    seed_demo_data: bool = False
    integration_lease_seconds: int = 60
    fixture_webhook_max_age_seconds: int = 300

    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="",
        case_sensitive=False,
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
