import pytest
from pydantic import ValidationError

from app.core.config import Settings


@pytest.fixture(autouse=True)
def _runtime_env_without_owner_url(monkeypatch):
    """Models a real staging/production runtime: the owner/migration URL is not present in the process environment."""
    monkeypatch.delenv("VAND_MIGRATION_DATABASE_URL", raising=False)

OIDC = dict(auth_mode="oidc", oidc_issuer="https://idp.example.com/", oidc_audience="vand", oidc_jwks_url="https://idp.example.com/jwks",
            oidc_client_id="cid", oidc_client_secret="csecret", session_encryption_key="x" * 44, public_base_url="https://app.example.com")
PROD_DB = dict(origin_auth_secret="o" * 40, scanner_backend="clamd", scan_required=True, database_url="postgresql+asyncpg://a:b@db.internal/x", worker_database_url="postgresql+asyncpg://a:b@db.internal/x",
               cors_origins="https://app.example.com", storage_backend="s3")


def test_dev_auth_refused_in_production():
    with pytest.raises(ValidationError, match="auth_mode=dev"):
        Settings(env="production", **PROD_DB)


def test_oidc_settings_required_in_production():
    with pytest.raises(ValidationError, match="OIDC"):
        Settings(env="staging", auth_mode="oidc", **PROD_DB)


def test_dev_database_and_local_storage_refused_in_production():
    with pytest.raises(ValidationError, match="Development database"):
        Settings(env="production", storage_backend="s3", scanner_backend="clamd", scan_required=True, origin_auth_secret="o" * 40, cors_origins="https://app.example.com", **OIDC)
    with pytest.raises(ValidationError, match="Local object storage"):
        Settings(env="production", **OIDC, **{**PROD_DB, "storage_backend": "local"})


def test_valid_production_config_accepted():
    assert Settings(env="production", **OIDC, **PROD_DB).env == "production"


def test_https_public_url_and_session_key_required_in_production():
    with pytest.raises(ValidationError, match="public_base_url"):
        Settings(env="production", **{**OIDC, "public_base_url": "http://app.example.com"}, **PROD_DB)
    with pytest.raises(ValidationError, match="session_encryption_key"):
        Settings(env="production", **{**OIDC, "session_encryption_key": ""}, **PROD_DB)


def test_scanner_required_in_production():
    with pytest.raises(ValidationError, match="malware scanner"):
        Settings(env="production", **OIDC, **{**PROD_DB, "scan_required": False})


def test_origin_secret_required_in_production():
    with pytest.raises(ValidationError, match="origin_auth_secret"):
        Settings(env="production", **OIDC, **{**PROD_DB, "origin_auth_secret": "short"})


def test_owner_credentials_must_not_exist_in_runtime_env():
    with pytest.raises(ValidationError, match="Owner/migration credentials"):
        Settings(env="production", **OIDC, **PROD_DB, migration_database_url="postgresql+psycopg://owner:x@db.internal/x")


def test_non_https_or_localhost_cors_origin_rejected_in_production():
    for bad in ("http://localhost:5173", "http://app.example.com"):
        with pytest.raises(ValidationError, match="cors_origins"):
            Settings(env="production", **OIDC, **{**PROD_DB, "cors_origins": bad})


def test_host_prefixed_cookie_in_staging_and_production_only():
    assert Settings(env="production", **OIDC, **PROD_DB).effective_cookie_name == "__Host-vand_session"
    assert Settings(env="local").effective_cookie_name == "vand_session"
