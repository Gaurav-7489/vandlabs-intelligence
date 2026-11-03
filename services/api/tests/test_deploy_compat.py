"""Compatibility checks for hosted services that can be verified without provisioning them."""
import os

import pytest
from sqlalchemy import text

from app.core.config import Settings, get_settings
from app.core.db import Database, make_engine, normalize_asyncpg_url

NEON = "postgresql+asyncpg://u:p@ep-x-pooler.ap-southeast-1.aws.neon.tech/db?sslmode=require&channel_binding=require"


@pytest.mark.parametrize("mode,expected", [("require", "require"), ("verify-full", "verify-full"), ("verify-ca", "require"),
                                           ("disable", None), ("prefer", None)])
def test_neon_style_urls_are_translated_for_asyncpg(mode, expected):
    url, args = normalize_asyncpg_url(NEON.replace("sslmode=require", f"sslmode={mode}"))
    assert "sslmode" not in url and "channel_binding" not in url  # asyncpg would reject these kwargs
    assert args.get("ssl") == expected  # TLS intent preserved, never silently dropped


async def test_pooler_mode_engine_runs_real_queries():
    """Transaction-pooler settings (no statement cache, unique statement names) must work with the installed drivers."""
    s = Settings(db_disable_statement_cache=True)
    db = Database(make_engine(get_settings().database_url, s))
    for _ in range(3):  # repeated identical statements: would fail with reused names behind a real pooler
        async with db.bare_session() as session:
            assert (await session.execute(text("SELECT 1 + :x"), {"x": 1})).scalar_one() == 2
    await db.dispose()


def test_r2_client_sends_checksums_only_when_required():
    from app.core.storage import S3Storage
    st = S3Storage(Settings(storage_backend="s3", s3_endpoint_url="https://acct.r2.cloudflarestorage.com", s3_bucket="b",
                            s3_access_key_id="k", s3_secret_access_key="s"))
    cfg = st.client.meta.config
    assert cfg.request_checksum_calculation == "when_required" and cfg.response_checksum_validation == "when_required"


def test_client_ip_header_only_trusted_from_edge():
    from app.identity.deps import client_ip

    class R:
        headers = {"x-vand-client-ip": "198.51.100.7"}
        client = type("C", (), {"host": "10.0.0.9"})()
        state = type("S", (), {"edge_trusted": False})()
    assert client_ip(R(), 1) == "10.0.0.9"  # type: ignore[arg-type]
    R.state = type("S", (), {"edge_trusted": True})()
    assert client_ip(R(), 1) == "198.51.100.7"  # type: ignore[arg-type]


@pytest.mark.parametrize("raw", ["postgresql://u:p@ep-x.neon.tech/db?sslmode=require&channel_binding=require",
                                 "postgres://u:p@ep-x.neon.tech/db?sslmode=require"])
def test_provider_urls_get_the_installed_drivers(raw):
    from app.core.db import with_driver
    url, args = normalize_asyncpg_url(raw)
    assert url.startswith("postgresql+asyncpg://") and args == {"ssl": "require"}
    assert with_driver(raw, "psycopg").startswith("postgresql+psycopg://")  # migrations/CLI (psycopg 3 understands sslmode)


async def test_migrations_and_cli_accept_a_plain_postgresql_url(owner_sql):
    """OWNER_DATABASE_URL exactly as a provider hands it out (no +driver)."""
    import subprocess
    import sys
    plain = os.environ["VAND_MIGRATION_DATABASE_URL"].replace("postgresql+psycopg://", "postgresql://")
    env = {**os.environ, "OWNER_DATABASE_URL": plain}
    env.pop("VAND_MIGRATION_DATABASE_URL")
    r = subprocess.run([sys.executable, "-m", "alembic", "current"], cwd=os.path.dirname(os.path.dirname(__file__)), env=env, capture_output=True, text=True)
    assert r.returncode == 0 and "0004" in r.stdout, r.stderr[-500:]
    r = subprocess.run([sys.executable, "-m", "app.cli", "create-platform-admin", f"cli-{os.getpid()}@vand.example.com"],
                       cwd=os.path.dirname(os.path.dirname(__file__)), env=env, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr[-500:]
