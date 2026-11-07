from functools import lru_cache

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

DEFAULT_AUTH_SECRET_KEY = "local-development-secret-change-me"
MIN_AUTH_SECRET_LENGTH = 32
CAPABILITY_FLAGS = ("ai", "workflows", "connectors", "agents")


class Settings(BaseSettings):
    app_name: str = "AI CRM API"
    app_version: str = "0.1.0"
    debug: bool = False
    database_url: str = "sqlite+aiosqlite:///./ai_crm_phase1.db"
    api_v1_prefix: str = "/api/v1"
    auth_secret_key: str = DEFAULT_AUTH_SECRET_KEY
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
    worker_enabled: bool = False
    worker_poll_seconds: float = Field(default=5.0, gt=0)
    worker_batch_size: int = Field(default=10, ge=1)
    proactive_check_interval_seconds: int = Field(default=300, ge=1)
    integration_sync_interval_seconds: int = Field(default=900, ge=1)
    agent_max_depth_cap: int = Field(default=3, ge=1)
    agent_max_fanout_cap: int = Field(default=3, ge=1)
    agent_token_budget_cap: int = Field(default=200000, ge=1)
    agent_step_budget_cap: int = Field(default=50, ge=1)
    agent_side_effect_budget_cap: int = Field(default=10, ge=0)
    agent_max_run_hours: int = Field(default=24, ge=1)
    agent_repeated_failure_threshold: int = Field(default=2, ge=1)
    agent_cost_per_1k_tokens_micros: int = Field(default=0, ge=0)
    disabled_capabilities: str = ""

    @property
    def disabled_capability_set(self) -> frozenset[str]:
        return frozenset(
            part.strip() for part in self.disabled_capabilities.split(",") if part.strip()
        )

    @model_validator(mode="after")
    def _validate_disabled_capabilities(self) -> "Settings":
        unknown = self.disabled_capability_set - set(CAPABILITY_FLAGS)
        if unknown:
            raise ValueError(f"Unknown DISABLED_CAPABILITIES entries: {sorted(unknown)}")
        return self

    @model_validator(mode="after")
    def _require_strong_secret_outside_debug(self) -> "Settings":
        if self.debug:
            return self
        if (
            self.auth_secret_key == DEFAULT_AUTH_SECRET_KEY
            or len(self.auth_secret_key) < MIN_AUTH_SECRET_LENGTH
        ):
            raise ValueError(
                f"AUTH_SECRET_KEY must be set to at least {MIN_AUTH_SECRET_LENGTH} characters "
                "and differ from the development default unless DEBUG=true"
            )
        return self

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
