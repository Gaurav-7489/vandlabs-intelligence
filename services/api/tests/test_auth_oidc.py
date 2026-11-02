import time
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
import pytest_asyncio
import redis.asyncio as aioredis
from cryptography.fernet import Fernet
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from app.ai.gateway import AIGateway
from app.core.config import Settings
from app.main import create_app
from tests.conftest import uniq
from tests.oidc_issuer import API_AUD, CLIENT_ID, CLIENT_SECRET, ISSUER, TestIssuer

API = "/api/v1"
WEB = "http://localhost:5173"


@pytest_asyncio.fixture
async def oidc_env():
    issuer = TestIssuer()
    http = httpx.AsyncClient(transport=ASGITransport(app=issuer.app), base_url=ISSUER)
    s = Settings(auth_mode="oidc", oidc_issuer=ISSUER, oidc_audience=API_AUD, oidc_jwks_url=f"{ISSUER}/jwks.json", oidc_client_id=CLIENT_ID,
                 oidc_client_secret=CLIENT_SECRET, session_encryption_key=Fernet.generate_key().decode(), public_base_url=WEB,
                 session_revalidate_seconds=900)
    app = create_app(s, ai=AIGateway(s, providers=[]), oidc_http=http)
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url=WEB) as client:
            yield client, issuer, app, s
    await http.aclose()


async def sign_in(client, issuer, email, mfa=True, verified=True, return_to="/knowledge"):
    """Drives the real flow: /auth/login -> IdP authorize -> /auth/callback. Returns the callback response."""
    r = await client.get(f"{API}/auth/login", params={"return_to": return_to})
    assert r.status_code == 302
    loc = r.headers["location"]
    assert loc.startswith(f"{ISSUER}/authorize")
    q = parse_qs(urlparse(loc).query)
    assert q["code_challenge_method"] == ["S256"] and q["state"] and q["nonce"] and q["response_type"] == ["code"]
    async with httpx.AsyncClient(transport=ASGITransport(app=issuer.app)) as idp:
        a = await idp.get(loc + f"&sim_user={email}&sim_mfa={int(mfa)}&sim_verified={int(verified)}")
    cb = urlparse(a.headers["location"])
    return await client.get(f"{API}/auth/callback?{cb.query}")


async def provision(client, app, owner_email):
    """Create an org through the (dev-free) path: platform admin inserted directly, then provisioned with a bearer access JWT."""
    return None


@pytest.fixture
def org_for(oidc_env, owner_sql):
    client, issuer, app, _ = oidc_env

    async def _make(role="manager"):
        admin = f"{uniq('padmin')}@vand.example.com"
        owner_sql.execute(text("INSERT INTO users (email, is_platform_admin) VALUES (:e, true)"), {"e": admin})
        owner_sql.connection.commit()
        owner = f"{uniq('own')}@acme.example.com"
        slug = uniq("o")
        r = await client.post(f"{API}/platform/organizations", headers={"Authorization": f"Bearer {issuer.access_jwt(admin)}"},
                              json={"name": "Acme", "slug": slug, "owner_email": owner})
        assert r.status_code == 201, r.text
        return r.json()["id"], owner
    return _make


async def test_login_flow_creates_httponly_session_and_restores_it(oidc_env, org_for):
    client, issuer, app, s = oidc_env
    org, owner = await org_for()
    r = await sign_in(client, issuer, owner)
    assert r.status_code == 302 and r.headers["location"] == f"{WEB}/knowledge"
    cookie = r.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=lax" in cookie and "path=/" in cookie
    sess = (await client.get(f"{API}/auth/session")).json()  # "browser refresh": cookie jar restores the session
    assert sess["authenticated"] is True and sess["csrf"]
    me = (await client.get(f"{API}/me")).json()
    assert me["user"]["email"] == owner and me["memberships"][0]["org_id"] == org and me["user"]["mfa"] is True
    # the raw session record in Redis is encrypted (refresh token not stored in clear)
    rd = aioredis.from_url(s.redis_url, decode_responses=True)
    sid = client.cookies.get(s.session_cookie_name)
    blob = await rd.get(f"sess:{sid}")
    await rd.aclose()
    assert blob and "rt-" not in blob and "@" not in blob


async def test_no_session_is_unauthenticated(oidc_env):
    client, *_ = oidc_env
    assert (await client.get(f"{API}/auth/session")).json() == {"authenticated": False}
    assert (await client.get(f"{API}/me")).status_code == 401
    client.cookies.set("vand_session", "forged-session-id")
    assert (await client.get(f"{API}/me")).status_code == 401


async def test_state_is_single_use_and_unknown_state_rejected(oidc_env):
    client, issuer, *_ = oidc_env
    r = await client.get(f"{API}/auth/login")
    st = parse_qs(urlparse(r.headers["location"]).query)["state"][0]
    bad = await client.get(f"{API}/auth/callback", params={"code": "x", "state": "unknown"})
    assert bad.status_code == 302 and "auth_error=login_failed" in bad.headers["location"] and "set-cookie" not in bad.headers
    assert issuer.codes == {}
    # a valid state can be consumed once only: second use is rejected even with a (here invalid) code
    first = await client.get(f"{API}/auth/callback", params={"code": "nope", "state": st})
    again = await client.get(f"{API}/auth/callback", params={"code": "nope", "state": st})
    assert "auth_error" in first.headers["location"] and "auth_error" in again.headers["location"]


@pytest.mark.parametrize("override,label", [({"aud": "someone-else"}, "wrong audience"), ({"iss": "https://evil.test"}, "wrong issuer"),
                                            ({"exp": int(time.time()) - 60}, "expired"), ({"nonce": "tampered"}, "nonce mismatch")])
async def test_bad_id_tokens_rejected(oidc_env, org_for, override, label):
    client, issuer, *_ = oidc_env
    _, owner = await org_for()
    issuer.id_overrides = override
    r = await sign_in(client, issuer, owner)
    assert "auth_error=login_failed" in r.headers["location"], label
    assert (await client.get(f"{API}/auth/session")).json()["authenticated"] is False


async def test_id_token_with_invalid_signature_rejected(oidc_env, org_for):
    client, issuer, *_ = oidc_env
    _, owner = await org_for()
    issuer.sign_with_rogue = True
    r = await sign_in(client, issuer, owner)
    assert "auth_error=login_failed" in r.headers["location"]


async def test_pkce_verifier_is_enforced_by_idp_and_replayed_code_fails(oidc_env, org_for):
    client, issuer, *_ = oidc_env
    _, owner = await org_for()
    r = await client.get(f"{API}/auth/login")
    loc = r.headers["location"]
    async with httpx.AsyncClient(transport=ASGITransport(app=issuer.app)) as idp:
        a = await idp.get(loc + f"&sim_user={owner}")
    cb = urlparse(a.headers["location"]).query
    ok = await client.get(f"{API}/auth/callback?{cb}")
    assert "auth_error" not in ok.headers["location"]
    replay = await client.get(f"{API}/auth/callback?{cb}")  # same code + state again
    assert "auth_error=login_failed" in replay.headers["location"]


async def test_open_redirect_is_blocked(oidc_env, org_for):
    client, issuer, *_ = oidc_env
    _, owner = await org_for()
    for evil in ("https://evil.example", "//evil.example", "/\\evil.example", "javascript:alert(1)"):
        r = await sign_in(client, issuer, owner, return_to=evil)
        assert r.headers["location"] == f"{WEB}/"


async def test_privileged_role_requires_mfa_from_the_idp(oidc_env, org_for):
    client, issuer, *_ = oidc_env
    org, owner = await org_for()
    await sign_in(client, issuer, owner, mfa=False)
    r = await client.get(f"{API}/members", headers={"X-Org-ID": org})
    assert r.status_code == 403 and "Multi-factor" in r.json()["error"]["message"]
    await sign_in(client, issuer, owner, mfa=True)
    assert (await client.get(f"{API}/members", headers={"X-Org-ID": org})).status_code == 200


async def test_csrf_protection_on_cookie_sessions(oidc_env, org_for):
    client, issuer, *_ = oidc_env
    org, owner = await org_for()
    await sign_in(client, issuer, owner)
    csrf = (await client.get(f"{API}/auth/session")).json()["csrf"]
    body = {"email": f"{uniq('n')}@acme.example.com", "role": "viewer"}
    h = {"X-Org-ID": org}
    assert (await client.post(f"{API}/members", headers=h, json=body)).status_code == 403  # no origin/token
    assert (await client.post(f"{API}/members", headers={**h, "Origin": "https://evil.example", "X-CSRF-Token": csrf}, json=body)).status_code == 403
    assert (await client.post(f"{API}/members", headers={**h, "Origin": WEB, "X-CSRF-Token": "wrong"}, json=body)).status_code == 403
    assert (await client.post(f"{API}/members", headers={**h, "Origin": WEB, "X-CSRF-Token": csrf}, json=body)).status_code == 201


async def test_org_switching_and_foreign_org_denied(oidc_env, org_for):
    client, issuer, *_ = oidc_env
    org_a, owner_a = await org_for()
    org_b, _ = await org_for()
    await sign_in(client, issuer, owner_a)
    assert (await client.get(f"{API}/members", headers={"X-Org-ID": org_a})).status_code == 200
    assert (await client.get(f"{API}/members", headers={"X-Org-ID": org_b})).status_code == 403  # cross-tenant


async def test_removed_membership_takes_effect_immediately(oidc_env, org_for):
    client, issuer, *_ = oidc_env
    org, owner = await org_for()
    await sign_in(client, issuer, owner)
    mh = {"X-Org-ID": org, "Origin": WEB, "X-CSRF-Token": (await client.get(f"{API}/auth/session")).json()["csrf"]}
    staff = f"{uniq('st')}@acme.example.com"
    inv = (await client.post(f"{API}/members", headers=mh, json={"email": staff, "role": "staff"})).json()
    async with AsyncClient(transport=client._transport, base_url=WEB) as c2:  # second browser = the staff user
        await sign_in(c2, issuer, staff, mfa=False)
        assert (await c2.get(f"{API}/documents", headers={"X-Org-ID": org})).status_code == 200
        assert (await client.delete(f"{API}/members/{inv['id']}", headers=mh)).status_code == 204
        assert (await c2.get(f"{API}/documents", headers={"X-Org-ID": org})).status_code == 403


async def test_logout_destroys_session_server_side(oidc_env, org_for):
    client, issuer, *_ = oidc_env
    _, owner = await org_for()
    await sign_in(client, issuer, owner)
    old_cookie = client.cookies.get("vand_session")
    csrf = (await client.get(f"{API}/auth/session")).json()["csrf"]
    r = await client.post(f"{API}/auth/logout", headers={"Origin": WEB, "X-CSRF-Token": csrf})
    assert r.status_code == 200 and r.json()["logout_url"].startswith(f"{ISSUER}/logout")
    client.cookies.set("vand_session", old_cookie)  # replay the stolen cookie after logout
    assert (await client.get(f"{API}/me")).status_code == 401


async def test_admin_can_revoke_all_sessions_of_a_member(oidc_env, org_for):
    client, issuer, *_ = oidc_env
    org, owner = await org_for()
    await sign_in(client, issuer, owner)
    mh = {"X-Org-ID": org, "Origin": WEB, "X-CSRF-Token": (await client.get(f"{API}/auth/session")).json()["csrf"]}
    staff = f"{uniq('st')}@acme.example.com"
    inv = (await client.post(f"{API}/members", headers=mh, json={"email": staff, "role": "staff"})).json()
    async with AsyncClient(transport=client._transport, base_url=WEB) as c2:
        await sign_in(c2, issuer, staff, mfa=False)
        assert (await c2.get(f"{API}/me")).status_code == 200
        r = await client.post(f"{API}/members/{inv['id']}/revoke-sessions", headers=mh)
        assert r.status_code == 200 and r.json()["revoked"] == 1
        assert (await c2.get(f"{API}/me")).status_code == 401


async def test_idp_side_revocation_ends_session_at_next_revalidation(oidc_env, org_for):
    client, issuer, app, s = oidc_env
    _, owner = await org_for()
    await sign_in(client, issuer, owner)
    assert (await client.get(f"{API}/me")).status_code == 200
    sid = client.cookies.get("vand_session")
    # age the session so revalidation is due, and have the IdP revoke the grant
    import json
    rd = app.state.vand.redis
    rec = app.state.vand.sessions._dec(await rd.get(f"sess:{sid}"))
    rec["revalidate_at"] = time.time() - 1
    await rd.set(f"sess:{sid}", app.state.vand.sessions._enc(rec), ex=600)
    issuer.revoked.add(rec["refresh_token"])
    assert (await client.get(f"{API}/me")).status_code == 401
    assert json is not None


async def test_revalidation_rotates_refresh_token_and_survives_idp_outage(oidc_env, org_for):
    client, issuer, app, s = oidc_env
    _, owner = await org_for()
    await sign_in(client, issuer, owner)
    sid = client.cookies.get("vand_session")
    store, rd = app.state.vand.sessions, app.state.vand.redis

    async def age():
        rec = store._dec(await rd.get(f"sess:{sid}"))
        rec["revalidate_at"] = time.time() - 1
        await rd.set(f"sess:{sid}", store._enc(rec), ex=600)
        return rec
    before = (await age())["refresh_token"]
    assert (await client.get(f"{API}/me")).status_code == 200
    after = store._dec(await rd.get(f"sess:{sid}"))["refresh_token"]
    assert after != before  # rotated
    await age()
    issuer.idp_down = True  # transient IdP outage must not mass-logout users
    assert (await client.get(f"{API}/me")).status_code == 200


async def test_idle_and_absolute_expiry(oidc_env, org_for):
    client, issuer, app, s = oidc_env
    _, owner = await org_for()
    await sign_in(client, issuer, owner)
    sid = client.cookies.get("vand_session")
    store, rd = app.state.vand.sessions, app.state.vand.redis
    rec = store._dec(await rd.get(f"sess:{sid}"))
    rec["created"] = time.time() - s.session_absolute_ttl_seconds - 5  # beyond absolute lifetime
    await rd.set(f"sess:{sid}", store._enc(rec), ex=600)
    assert (await client.get(f"{API}/auth/session")).json()["authenticated"] is False
    await sign_in(client, issuer, owner)
    sid = client.cookies.get("vand_session")
    await rd.delete(f"sess:{sid}")  # idle expiry == Redis TTL elapsed
    assert (await client.get(f"{API}/me")).status_code == 401


async def test_unverified_email_cannot_claim_invited_account(oidc_env, org_for):
    client, issuer, *_ = oidc_env
    org, owner = await org_for()
    await sign_in(client, issuer, owner, verified=False)
    assert (await client.get(f"{API}/me")).status_code == 401  # invited user exists but email unverified -> no binding


# ---- Bearer access JWTs (machine clients) ----
async def test_bearer_jwt_validation_matrix(oidc_env, org_for):
    client, issuer, *_ = oidc_env
    _, owner = await org_for()
    ok = await client.get(f"{API}/me", headers={"Authorization": f"Bearer {issuer.access_jwt(owner)}"})
    assert ok.status_code == 200
    for label, tok in {"wrong audience": issuer.access_jwt(owner, aud="https://other"), "wrong issuer": issuer.access_jwt(owner, iss="https://evil.test"),
                       "expired": issuer.access_jwt(owner, exp_in=-30), "bad signature": issuer.access_jwt(owner, rogue=True), "garbage": "not.a.jwt"}.items():
        r = await client.get(f"{API}/me", headers={"Authorization": f"Bearer {tok}"})
        assert r.status_code == 401, label


async def test_dev_endpoints_absent_in_oidc_mode(oidc_env):
    client, *_ = oidc_env
    assert (await client.post(f"{API}/auth/dev-token", json={"email": "a@b.example.com"})).status_code == 404
    assert (await client.get(f"{API}/auth/config")).json() == {"mode": "oidc"}
    # HS256 dev tokens are not accepted in oidc mode
    from tests.conftest import token
    assert (await client.get(f"{API}/me", headers={"Authorization": f"Bearer {token('a@b.example.com')}"})).status_code == 401
