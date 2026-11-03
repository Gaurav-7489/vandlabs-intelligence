import os

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError, ProgrammingError

from tests.conftest import uniq

APP = os.environ["VAND_DATABASE_URL"].replace("+asyncpg", "+psycopg")


def _count(c, sql, **p):
    return c.execute(text(sql), p).scalar_one()


async def test_users_visible_only_within_tenant_scope(client, make_env):
    a, b = await make_env("ua"), await make_env("ub")
    eng = create_engine(APP)
    with eng.begin() as c:  # no context at all: nobody
        assert _count(c, "SELECT count(*) FROM users") == 0
    with eng.begin() as c:  # tenant A context: exactly A's members, never B's
        c.execute(text("SELECT set_config('app.org_id', :o, true)"), {"o": a.org_id})
        emails = set(c.execute(text("SELECT email FROM users")).scalars())
        assert emails == set(a.users.values())
        assert not (emails & set(b.users.values()))
    with eng.begin() as c:  # a forgotten WHERE in tenant code can no longer dump other tenants' emails
        c.execute(text("SELECT set_config('app.org_id', :o, true)"), {"o": a.org_id})
        assert _count(c, "SELECT count(*) FROM users WHERE email = :e", e=b.users["owner"]) == 0


async def test_users_cannot_be_created_or_rebound_outside_identity_step(client, make_env):
    env = await make_env("uw")
    eng = create_engine(APP)
    with pytest.raises((DBAPIError, ProgrammingError)), eng.begin() as c:
        c.execute(text("SELECT set_config('app.org_id', :o, true)"), {"o": env.org_id})
        c.execute(text("INSERT INTO users (email) VALUES (:e)"), {"e": f"{uniq('x')}@x.example.com"})
    with eng.begin() as c:  # UPDATE outside the identity step silently matches 0 rows (USING clause)
        c.execute(text("SELECT set_config('app.org_id', :o, true)"), {"o": env.org_id})
        n = c.execute(text("UPDATE users SET subject = 'hijack' WHERE email = :e"), {"e": env.users["staff"]}).rowcount
        assert n == 0
    with eng.begin() as c:  # no DELETE policy: runtime role can never delete users
        c.execute(text("SELECT set_config('app.identity_resolution', 'on', true)"))
        assert c.execute(text("DELETE FROM users WHERE email = :e"), {"e": env.users["staff"]}).rowcount == 0


async def test_invitation_still_works_for_a_user_from_another_tenant(client, make_env):
    a, b = await make_env("inv-a"), await make_env("inv-b")
    r = await client.post("/api/v1/members", headers=a.h("owner"), json={"email": b.users["staff"], "role": "viewer"})
    assert r.status_code == 201  # identity step finds the existing user; no duplicate account is created


@pytest.mark.parametrize("stmt", ["INSERT INTO tasks (org_id, title) SELECT id, 'x' FROM organizations LIMIT 1",
                                  "UPDATE documents SET filename = 'x'", "DELETE FROM audit_events", "TRUNCATE jobs"])
async def test_backup_role_is_read_only(stmt, admin_sql):
    eng = create_engine("postgresql+psycopg://vand_backup:dev_backup_pw@localhost:5432/vand_test")  # pragma: allowlist secret
    try:
        with pytest.raises((DBAPIError, ProgrammingError)), eng.begin() as c:
            c.execute(text(stmt))
    finally:
        eng.dispose()


async def test_backup_role_is_refused_as_a_runtime_role(admin_sql):
    from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
    from app.core.dbsafety import check_role_safety
    eng = create_async_engine("postgresql+asyncpg://vand_backup:dev_backup_pw@localhost:5432/vand_test")  # pragma: allowlist secret
    async with AsyncSession(eng) as s:
        r = await check_role_safety(s)
    await eng.dispose()
    assert "role has BYPASSRLS" in r.problems
