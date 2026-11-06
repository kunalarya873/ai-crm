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
    knowledge_chunk_size: int = 1200
    knowledge_lease_seconds: int = 60
    job_default_lease_seconds: int = 60
    job_default_timeout_seconds: int = 300
    job_max_backoff_seconds: int = 3600
    ai_provider_key: str = "fixture"
    ai_model_key: str = "fixture-text-v1"
    ai_config_version: str = "phase6-local-v1"
    ai_prompt_catalog_version: str = "phase6-v1"
    ai_timeout_seconds: int = 10
    ai_max_attempts: int = 2
    ai_retry_delay_seconds: float = 0.05
    ai_max_output_chars: int = 12000
    ai_cost_per_1k_input_micros: int = 0
    ai_cost_per_1k_output_micros: int = 0
    action_default_expiration_hours: int = 24
    action_timeout_seconds: int = 30
    action_max_attempts: int = 3
    proactive_inactive_opportunity_days: int = 30
    proactive_alert_suppression_minutes: int = 60
    observability_retention_days: int = 90

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
