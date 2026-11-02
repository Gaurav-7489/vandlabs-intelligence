import os

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.core.dbsafety import check_role_safety


async def _check(url: str):
    eng = create_async_engine(url)
    async with AsyncSession(eng) as s:
        r = await check_role_safety(s)
    await eng.dispose()
    return r


async def test_app_and_worker_roles_are_safe():
    for var in ("VAND_DATABASE_URL", "VAND_WORKER_DATABASE_URL"):
        r = await _check(os.environ[var])
        assert r.ok, (var, r.problems)


async def test_owner_role_is_flagged_unsafe():
    r = await _check(os.environ["VAND_MIGRATION_DATABASE_URL"].replace("+psycopg", "+asyncpg"))
    assert not r.ok and any("owns tenant tables" in p for p in r.problems)


async def test_superuser_and_bypassrls_flagged(owner_sql):
    from sqlalchemy import text
    owner_sql.execute(text("SELECT 1"))
    pytest.importorskip("asyncpg")
    # postgres superuser is not reachable with test credentials; verify the BYPASSRLS branch via a throwaway role instead
    import subprocess
    sql = "DROP ROLE IF EXISTS vand_rogue; CREATE ROLE vand_rogue LOGIN PASSWORD 'x' BYPASSRLS; GRANT USAGE ON SCHEMA public TO vand_rogue;"
    res = subprocess.run(["su", "postgres", "-c", f"psql -d vand_test -c \"{sql}\""], capture_output=True)
    if res.returncode != 0:
        pytest.skip("cannot create throwaway role in this environment")
    try:
        r = await _check("postgresql+asyncpg://vand_rogue:x@localhost:5432/vand_test")
        assert "role has BYPASSRLS" in r.problems
    finally:
        subprocess.run(["su", "postgres", "-c", "psql -d vand_test -c \"REVOKE ALL ON SCHEMA public FROM vand_rogue; DROP ROLE vand_rogue\""], capture_output=True)


async def test_readyz_reports_db_role(client):
    r = await client.get("/readyz")
    assert r.json()["checks"]["db_role"] == "ok"
