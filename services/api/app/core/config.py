"""Typed, explicit configuration. Secrets come from the environment only."""
from functools import lru_cache
from typing import Literal

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="VAND_", env_file=".env", extra="ignore")

    env: Literal["local", "test", "staging", "production"] = "local"

    # Database: the API connects as a NON-owner role so Row-Level Security applies.
    database_url: str = "postgresql+asyncpg://vand_app:dev_app_pw@localhost:5432/vand_dev"
    worker_database_url: str = "postgresql+asyncpg://vand_worker:dev_worker_pw@localhost:5432/vand_dev"
    migration_database_url: str = "postgresql+psycopg://vand_owner:dev_owner_pw@localhost:5432/vand_dev"
    db_pool_size: int = 5
    db_max_overflow: int = 5
    # Required when connecting through a transaction-mode pooler (e.g. Neon pooled endpoint).
    db_disable_statement_cache: bool = False

    redis_url: str = "redis://localhost:6379/0"

    # Authentication (OIDC). "dev" mode is HS256 with a local secret and is refused in staging/production.
    auth_mode: Literal["oidc", "dev"] = "dev"
    oidc_issuer: str = ""
    oidc_audience: str = ""
    oidc_jwks_url: str = ""
    dev_jwt_secret: str = "dev-only-secret-change-me-32-bytes-min!!"  # noqa: S105 - dev mode is rejected in staging/production
    require_mfa_for_privileged: bool = True

    # Storage
    storage_backend: Literal["local", "s3"] = "local"
    storage_local_dir: str = "./.data/objects"
    s3_endpoint_url: str = ""  # Cloudflare R2: https://<account>.r2.cloudflarestorage.com
    s3_bucket: str = ""
    s3_access_key_id: str = ""
    s3_secret_access_key: str = ""

    # Upload limits
    max_upload_bytes: int = 25 * 1024 * 1024
    max_parse_rows: int = 50_000
    max_parse_chars: int = 5_000_000
    max_zip_expansion_ratio: int = 100  # DOCX/XLSX are zip containers: guard against archive bombs

    # AI gateway: providers are configured, never assumed.
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-haiku-5-5"
    openai_api_key: str = ""
    openai_model: str = ""
    ai_provider_order: str = "anthropic,openai"
    ai_max_input_chars: int = 24_000
    ai_max_output_tokens: int = 800
    ai_timeout_seconds: float = 30.0
    ai_org_daily_token_budget: int = 200_000

    # Risk rules
    risk_due_soon_days: int = 14

    cors_origins: str = "http://localhost:5173"
    trusted_proxy_hops: int = 1

    @model_validator(mode="after")
    def _guard_production(self) -> "Settings":
        if self.env in ("staging", "production"):
            if self.auth_mode == "dev":
                raise ValueError("auth_mode=dev is not permitted outside local/test")
            if not (self.oidc_issuer and self.oidc_audience and self.oidc_jwks_url):
                raise ValueError("OIDC issuer, audience and JWKS URL are required")
        return self

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
