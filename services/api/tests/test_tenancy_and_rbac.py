import os

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError, ProgrammingError

from tests.conftest import hdr, sample_csv, token, uniq

API = "/api/v1"


async def test_unauthenticated_rejected(client):
    assert (await client.get(f"{API}/documents")).status_code == 401
    r = await client.get(f"{API}/me", headers={"Authorization": "Bearer garbage"})
    assert r.status_code == 401 and r.json()["error"]["code"] == "unauthenticated"


async def test_expired_token_rejected(client):
    r = await client.get(f"{API}/me", headers={"Authorization": f"Bearer {token('a@b.example.com', exp_delta=-10)}"})
    assert r.status_code == 401


async def test_cross_tenant_access_denied_and_indistinguishable(client, make_env):
    a, b = await make_env("alpha"), await make_env("beta")
    r = await client.post(f"{API}/documents", headers=b.h("manager"), files={"file": ("a.csv", sample_csv(), "text/csv")})
    assert r.status_code == 202
    # A's owner cannot use B's org id at all; response is identical to a non-existent org.
    forged = {**hdr(a.users["owner"]), "X-Org-ID": b.org_id}
    r1 = await client.get(f"{API}/documents", headers=forged)
    r2 = await client.get(f"{API}/documents", headers={**hdr(a.users["owner"]), "X-Org-ID": "00000000-0000-0000-0000-000000000000"})
    assert r1.status_code == r2.status_code == 403 and r1.json()["error"]["message"] == r2.json()["error"]["message"]
    # IDOR: B's document id requested under A's own org context -> 404, not 403 (no existence leak).
    doc_id = r.json()["id"]
    assert (await client.get(f"{API}/documents/{doc_id}", headers=a.h("owner"))).status_code == 404
    assert (await client.get(f"{API}/documents/{doc_id}", headers=b.h("viewer"))).status_code == 200


async def test_rls_blocks_cross_tenant_reads_and_writes_at_database_level(client, make_env):
    """Defense in depth: even raw SQL as the app role cannot see/write another tenant's rows."""
    a, b = await make_env("rls-a"), await make_env("rls-b")
    await client.post(f"{API}/documents", headers=b.h("manager"), files={"file": ("b.csv", sample_csv(), "text/csv")})
    eng = create_engine(os.environ["VAND_DATABASE_URL"].replace("+asyncpg", "+psycopg"))
    with eng.begin() as c:
        c.execute(text("SELECT set_config('app.org_id', :o, true)"), {"o": a.org_id})
        assert c.execute(text("SELECT count(*) FROM documents")).scalar_one() == 0
        assert c.execute(text("SELECT count(*) FROM documents WHERE org_id = :o"), {"o": b.org_id}).scalar_one() == 0
    with eng.begin() as c:  # no tenant context at all -> nothing visible (and no cast error on reused connections)
        assert c.execute(text("SELECT count(*) FROM documents")).scalar_one() == 0
    with pytest.raises(DBAPIError), eng.begin() as c:  # WITH CHECK prevents writing into another tenant
        c.execute(text("SELECT set_config('app.org_id', :o, true)"), {"o": a.org_id})
        c.execute(text("INSERT INTO tasks (org_id, title) VALUES (:o, 'x')"), {"o": b.org_id})


async def test_platform_admin_cannot_read_tenant_content(owner_sql, make_env):
    await make_env("pa")
    eng = create_engine(os.environ["VAND_DATABASE_URL"].replace("+asyncpg", "+psycopg"))
    with eng.begin() as c:
        c.execute(text("SELECT set_config('app.platform', 'true', true)"))
        assert c.execute(text("SELECT count(*) FROM organizations")).scalar_one() >= 1
        assert c.execute(text("SELECT count(*) FROM memberships")).scalar_one() == 0
        assert c.execute(text("SELECT count(*) FROM documents")).scalar_one() == 0


async def test_audit_log_is_append_only(client, make_env):
    env = await make_env("aud")
    eng = create_engine(os.environ["VAND_DATABASE_URL"].replace("+asyncpg", "+psycopg"))
    with pytest.raises((ProgrammingError, DBAPIError)), eng.begin() as c:
        c.execute(text("SELECT set_config('app.org_id', :o, true)"), {"o": env.org_id})
        c.execute(text("UPDATE audit_events SET action='tampered'"))
    with pytest.raises((ProgrammingError, DBAPIError)), eng.begin() as c:
        c.execute(text("DELETE FROM audit_events"))


async def test_roles_enforced_server_side(client, make_env):
    env = await make_env("rbac")
    up = lambda role: client.post(f"{API}/documents", headers=env.h(role), files={"file": (f"{uniq('f')}.txt", uniq("x").encode(), "text/plain")})  # noqa: E731
    assert (await up("viewer")).status_code == 403
    assert (await up("auditor")).status_code == 403
    assert (await up("staff")).status_code == 202
    assert (await client.get(f"{API}/audit", headers=env.h("staff"))).status_code == 403
    assert (await client.get(f"{API}/audit", headers=env.h("auditor"))).status_code == 200
    assert (await client.get(f"{API}/members", headers=env.h("staff"))).status_code == 403
    # a role claimed by the client is ignored: role always comes from the database
    forged = {**env.h("viewer"), "X-Role": "owner"}
    assert (await client.post(f"{API}/members", headers=forged, json={"email": "z@z.example.com", "role": "viewer"})).status_code == 403


async def test_mfa_required_for_privileged_roles(client, make_env):
    env = await make_env("mfa")
    r = await client.get(f"{API}/members", headers=env.h("owner", mfa=False))
    assert r.status_code == 403 and r.json()["error"]["message"].startswith("Multi-factor")
    assert (await client.get(f"{API}/members", headers=env.h("owner", mfa=True))).status_code == 200
    assert (await client.get(f"{API}/documents", headers=env.h("staff", mfa=False))).status_code == 200


async def test_role_escalation_and_last_owner_protection(client, make_env):
    env = await make_env("esc")
    # admin cannot mint owners/admins
    r = await client.post(f"{API}/members", headers=env.h("admin"), json={"email": f"{uniq('n')}@x.example.com", "role": "owner"})
    assert r.status_code == 403
    members = (await client.get(f"{API}/members", headers=env.h("owner"))).json()["items"]
    owner_m = next(m for m in members if m["role"] == "owner")
    r = await client.patch(f"{API}/members/{owner_m['id']}", headers=env.h("owner"), json={"role": "viewer"})
    assert r.status_code == 409  # cannot demote the last owner
    admin_m = next(m for m in members if m["role"] == "admin")
    assert (await client.patch(f"{API}/members/{admin_m['id']}", headers=env.h("admin"), json={"role": "viewer"})).status_code == 403
    assert (await client.delete(f"{API}/members/{owner_m['id']}", headers=env.h("owner"))).status_code == 409


async def test_non_platform_admin_cannot_provision_orgs(client, make_env):
    env = await make_env("np")
    r = await client.post(f"{API}/platform/organizations", headers=hdr(env.users["owner"]),
                          json={"name": "Evil", "slug": uniq("evil"), "owner_email": "e@e.example.com"})
    assert r.status_code == 403


async def test_invited_user_binds_only_with_verified_email(client, make_env):
    env = await make_env("bind")
    r = await client.get(f"{API}/me", headers={"Authorization": f"Bearer {token(env.users['staff'], verified=False, sub='attacker')}"})
    # unverified email must NOT claim the invited identity -> treated as conflict, no memberships
    assert r.status_code == 401
    me = (await client.get(f"{API}/me", headers=env.h("staff"))).json()
    assert [m["org_id"] for m in me["memberships"]] == [env.org_id]


async def test_error_responses_do_not_leak_internals(client, make_env):
    env = await make_env("err")
    r = await client.get(f"{API}/documents/not-a-uuid", headers=env.h("owner"))
    assert r.status_code == 422 and "Traceback" not in r.text and "sqlalchemy" not in r.text.lower()
    assert r.headers["x-content-type-options"] == "nosniff" and r.headers["cache-control"] == "no-store" and "x-request-id" in r.headers


async def test_invited_user_subject_binding_is_persisted(client, make_env, owner_sql):
    env = await make_env("persist")
    await client.get(f"{API}/me", headers=env.h("staff"))
    row = owner_sql.execute(text("SELECT subject FROM users WHERE email = :e"), {"e": env.users["staff"]}).one()
    assert row[0] == f"sub-{env.users['staff']}"
