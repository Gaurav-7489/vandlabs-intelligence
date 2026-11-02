import pytest
from pydantic import ValidationError

from app.core.config import Settings

OIDC = dict(auth_mode="oidc", oidc_issuer="https://idp.example.com/", oidc_audience="vand", oidc_jwks_url="https://idp.example.com/jwks",
            oidc_client_id="cid", oidc_client_secret="csecret", session_encryption_key="x" * 44, public_base_url="https://app.example.com")
PROD_DB = dict(scanner_backend="clamd", scan_required=True, database_url="postgresql+asyncpg://a:b@db.internal/x", worker_database_url="postgresql+asyncpg://a:b@db.internal/x",
               migration_database_url="postgresql+psycopg://a:b@db.internal/x", storage_backend="s3")


def test_dev_auth_refused_in_production():
    with pytest.raises(ValidationError, match="auth_mode=dev"):
        Settings(env="production", **PROD_DB)


def test_oidc_settings_required_in_production():
    with pytest.raises(ValidationError, match="OIDC"):
        Settings(env="staging", auth_mode="oidc", **PROD_DB)


def test_dev_database_and_local_storage_refused_in_production():
    with pytest.raises(ValidationError, match="Development database"):
        Settings(env="production", storage_backend="s3", **OIDC)
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
