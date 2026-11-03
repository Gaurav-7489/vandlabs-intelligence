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


@pytest.mark.parametrize("attr,expected", [("BYPASSRLS", "role has BYPASSRLS"), ("SUPERUSER", "role is a superuser")])
async def test_privileged_roles_are_flagged_unsafe(admin_sql, attr, expected):
    """Runs in CI too (superuser available via VAND_TEST_ADMIN_URL): a role that could bypass RLS must be detected."""
    admin_sql("DROP ROLE IF EXISTS vand_rogue")
    admin_sql(f"CREATE ROLE vand_rogue LOGIN PASSWORD 'x' {attr}")
    admin_sql("GRANT USAGE ON SCHEMA public TO vand_rogue")
    try:
        r = await _check("postgresql+asyncpg://vand_rogue:x@localhost:5432/vand_test")
        assert expected in r.problems and not r.ok
    finally:
        admin_sql("REVOKE ALL ON SCHEMA public FROM vand_rogue")
        admin_sql("DROP ROLE vand_rogue")


async def test_rls_actually_blocks_a_normal_role_but_not_a_bypassrls_role(admin_sql, make_env, client):
    """The invariant itself, not just the detector: tenant rows are invisible to the app role and visible to a BYPASSRLS role."""
    env = await make_env("bypass")
    await client.post("/api/v1/tasks", headers=env.h("staff"), json={"title": "RLS probe task"})
    admin_sql("DROP ROLE IF EXISTS vand_rogue")
    admin_sql("CREATE ROLE vand_rogue LOGIN PASSWORD 'x' BYPASSRLS")
    admin_sql("GRANT USAGE ON SCHEMA public TO vand_rogue")
    admin_sql("GRANT SELECT ON ALL TABLES IN SCHEMA public TO vand_rogue")
    try:
        from sqlalchemy import text
        for url, expect_visible in ((os.environ["VAND_DATABASE_URL"], False), ("postgresql+asyncpg://vand_rogue:x@localhost:5432/vand_test", True)):
            eng = create_async_engine(url)
            async with eng.begin() as c:
                n = (await c.execute(text("SELECT count(*) FROM tasks WHERE title = 'RLS probe task'"))).scalar_one()
            await eng.dispose()
            assert (n > 0) is expect_visible
    finally:
        admin_sql("REVOKE ALL ON ALL TABLES IN SCHEMA public FROM vand_rogue")
        admin_sql("REVOKE ALL ON SCHEMA public FROM vand_rogue")
        admin_sql("DROP ROLE vand_rogue")


async def test_readyz_reports_db_role(client):
    r = await client.get("/readyz")
    assert r.json()["checks"]["db_role"] == "ok"
