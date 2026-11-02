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
    # Backend-for-Frontend session flow (Authorization Code + PKCE, confidential client).
    oidc_client_id: str = ""
    oidc_client_secret: str = ""
    oidc_authorize_url: str = ""  # optional: discovered from {issuer}/.well-known/openid-configuration when empty
    oidc_token_url: str = ""
    oidc_end_session_url: str = ""
    oidc_scopes: str = "openid profile email offline_access"
    oidc_extra_authorize_params: str = ""  # e.g. "audience=https://api.vandlabs.example" (Auth0)
    oidc_mfa_amr_values: str = "mfa,otp,hwk"
    public_base_url: str = "http://localhost:5173"  # browser-visible origin (same-origin proxy to /api)
    session_cookie_name: str = "vand_session"
    session_absolute_ttl_seconds: int = 8 * 3600
    session_idle_ttl_seconds: int = 1800
    session_revalidate_seconds: int = 900  # how often the IdP is asked whether the session is still valid
    session_encryption_key: str = ""  # Fernet key; required in staging/production (protects refresh tokens in Redis)
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

    # Untrusted-file handling
    parser_timeout_seconds: float = 30.0
    parser_memory_mb: int = 1024  # additional memory budget for parsing, on top of the interpreter/library baseline
    parser_cpu_seconds: int = 20
    parser_isolate_network: bool = True  # run the parser in its own (empty) network namespace via `unshare -rn` when available
    scanner_backend: Literal["none", "clamd"] = "none"
    clamd_host: str = "localhost"
    clamd_port: int = 3310
    scan_required: bool = False  # True => files stay unindexed until a scan has actually passed (forced on in staging/production)
    max_queued_jobs_per_org: int = 500

    # AI gateway: providers are configured, never assumed.
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-haiku-5-5"
    openai_api_key: str = ""
    openai_model: str = ""
    ai_provider_order: str = "anthropic,openai"
    ai_pricing_json: str = ""  # [{"model","input_per_mtok_usd","output_per_mtok_usd","effective_date","source"}]; empty => USD cost unavailable
    ai_max_input_chars: int = 24_000
    ai_max_output_tokens: int = 800
    ai_timeout_seconds: float = 30.0
    ai_org_daily_token_budget: int = 200_000

    # Risk rules
    risk_due_soon_days: int = 14

    cors_origins: str = "http://localhost:5173"
    trusted_proxy_hops: int = 1
    # Shared secret the Cloudflare Worker adds to origin requests. When set, requests without it are rejected (except health probes)
    # and CF-Connecting-IP is trusted only on authenticated edge requests.
    origin_auth_secret: str = ""

    @model_validator(mode="after")
    def _guard_production(self) -> "Settings":
        if self.env in ("staging", "production"):
            if self.auth_mode == "dev":
                raise ValueError("auth_mode=dev is not permitted outside local/test")
            if not (self.oidc_issuer and self.oidc_audience and self.oidc_jwks_url):
                raise ValueError("OIDC issuer, audience and JWKS URL are required")
            if any("dev_" in u or "localhost" in u for u in (self.database_url, self.worker_database_url, self.migration_database_url)):
                raise ValueError("Development database credentials/hosts are not permitted outside local/test")
            if len(self.origin_auth_secret) < 32:
                raise ValueError("origin_auth_secret (>=32 chars) is required outside local/test")
            if not (self.oidc_client_id and self.oidc_client_secret and self.session_encryption_key):
                raise ValueError("OIDC client id/secret and session_encryption_key are required")
            if not self.public_base_url.startswith("https://"):
                raise ValueError("public_base_url must be https outside local/test")
            if not self.scan_required or self.scanner_backend == "none":
                raise ValueError("A malware scanner (scanner_backend=clamd, scan_required=true) is required outside local/test")
            if self.storage_backend == "local":
                raise ValueError("Local object storage is not permitted outside local/test; configure S3/R2")
        return self

    @property
    def cookie_secure(self) -> bool:
        return self.env in ("staging", "production")

    @property
    def allowed_origins(self) -> set[str]:
        return {self.public_base_url.rstrip("/"), *self.cors_origin_list}

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
