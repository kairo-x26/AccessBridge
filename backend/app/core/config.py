"""Runtime configuration, loaded from environment variables prefixed ``AB_``."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="AB_", env_file=".env", extra="ignore")

    environment: Literal["development", "test", "production"] = "development"
    database_url: str = f"sqlite:///{BACKEND_ROOT / 'var' / 'accessbridge.db'}"
    storage_dir: Path = BACKEND_ROOT / "var" / "documents"

    # Auth
    jwt_secret: str = Field(default="dev-only-change-me-0123456789abcdef", min_length=32)
    jwt_issuer: str = "accessbridge"
    access_token_minutes: int = 30
    mfa_issuer: str = "AccessBridge AI"
    require_mfa: bool = False
    field_encryption_key: str | None = None

    # AI
    llm_provider: Literal["deterministic", "anthropic"] = "deterministic"
    llm_model: str = "claude-sonnet-5-5"
    anthropic_api_key: str | None = None
    llm_max_tokens_per_run: int = 20_000
    agent_max_tool_calls: int = 8

    # Messaging
    messaging_webhook_secret: str = "dev-webhook-secret-change-me"  # noqa: S105

    # Jobs
    job_max_attempts: int = 5
    job_lease_seconds: int = 60

    cors_origins: list[str] = ["http://localhost:3000"]
    log_level: str = "INFO"

    @model_validator(mode="after")
    def _no_dev_secrets_in_production(self) -> Settings:
        if self.environment == "production":
            if "dev" in self.jwt_secret or "dev" in self.messaging_webhook_secret:
                raise ValueError("development secrets must be replaced in production")
            if self.is_sqlite:
                raise ValueError("production requires PostgreSQL")
        return self

    @property
    def is_sqlite(self) -> bool:
        return self.database_url.startswith("sqlite")


@lru_cache
def get_settings() -> Settings:
    return Settings()
