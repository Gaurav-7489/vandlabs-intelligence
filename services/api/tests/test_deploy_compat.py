"""Compatibility checks for hosted services that can be verified without provisioning them."""
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
