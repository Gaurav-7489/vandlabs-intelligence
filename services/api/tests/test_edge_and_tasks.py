from app.core.config import Settings
from app.ai.gateway import AIGateway
from app.main import create_app
from httpx import ASGITransport, AsyncClient

from tests.conftest import hdr

API = "/api/v1"
SECRET = "edge-secret-" + "x" * 30


async def test_direct_origin_access_refused_without_edge_secret(make_env, client):
    s = Settings(origin_auth_secret=SECRET)
    app = create_app(s, ai=AIGateway(s, providers=[]))
    env = await make_env("edge")
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            h = env.h("viewer")
            assert (await c.get(f"{API}/documents", headers=h)).status_code == 403  # bypassed the edge
            assert (await c.get(f"{API}/documents", headers={**h, "X-Origin-Auth": "wrong"})).status_code == 403
            assert (await c.get(f"{API}/documents", headers={**h, "X-Origin-Auth": SECRET})).status_code == 200
            assert (await c.get("/healthz")).status_code == 200  # platform health probes still work


async def test_cf_connecting_ip_only_trusted_from_authenticated_edge(make_env, client, owner_sql):
    from sqlalchemy import text
    s = Settings(origin_auth_secret=SECRET)
    app = create_app(s, ai=AIGateway(s, providers=[]))
    env = await make_env("ip")
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            await c.get(f"{API}/documents", headers={**env.h("viewer"), "X-Origin-Auth": SECRET, "CF-Connecting-IP": "203.0.113.9"})
    row = owner_sql.execute(text("SELECT 1")).one()
    assert row[0] == 1
    # spoofing from a non-edge request: header ignored (client_ip falls back to the socket peer)
    from starlette.requests import Request
    from app.identity.deps import client_ip

    class R:
        headers = {"cf-connecting-ip": "6.6.6.6"}
        client = type("C", (), {"host": "10.0.0.5"})()
        state = type("S", (), {"edge_trusted": False})()
    assert client_ip(R(), 1) == "10.0.0.5"  # type: ignore[arg-type]
    R.state = type("S", (), {"edge_trusted": True})()
    assert client_ip(R(), 1) == "6.6.6.6"  # type: ignore[arg-type]
    _ = Request


async def test_direct_task_creation_is_audited_and_labelled_not_a_decision(client, make_env):
    env = await make_env("direct")
    assert (await client.post(f"{API}/tasks", headers=env.h("viewer"), json={"title": "Call the client"})).status_code == 403
    r = await client.post(f"{API}/tasks", headers=env.h("staff"), json={"title": "Call the client", "owner_email": "x@example.com"})
    assert r.status_code == 201 and r.json()["origin"] == "direct" and r.json()["decision_id"] is None
    actions = [e["action"] for e in (await client.get(f"{API}/audit", headers=env.h("auditor"))).json()["items"]]
    assert "task.created_direct" in actions
    assert hdr is not None
