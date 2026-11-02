import pytest
from pydantic import ValidationError

from app.core.config import Settings

OIDC = dict(auth_mode="oidc", oidc_issuer="https://idp.example.com/", oidc_audience="vand", oidc_jwks_url="https://idp.example.com/jwks")
PROD_DB = dict(database_url="postgresql+asyncpg://a:b@db.internal/x", worker_database_url="postgresql+asyncpg://a:b@db.internal/x",
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
