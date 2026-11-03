"""Browser authentication (BFF): Authorization Code + PKCE against the configured OIDC provider.

State/nonce/PKCE verifier live server-side (single-use, 10 min). The browser only ever receives an opaque HttpOnly session cookie."""
import json
import secrets
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, RedirectResponse, Response

from app.audit import service as audit
from app.core import metrics
from app.core.errors import Conflict, Unavailable
from app.core.logging import get_logger
from app.core.state import AppState, get_state
from app.identity.deps import Identity, client_ip, get_identity
from app.identity.oidc import OidcError, pkce_pair

router = APIRouter(prefix="/auth", tags=["auth"])
log = get_logger("auth")


def safe_return_to(v: str | None) -> str:
    """Only same-origin relative paths: blocks open redirects (`//evil`, `/\\evil`, `https://evil`)."""
    if not v or not v.startswith("/") or v.startswith("//") or "\\" in v or "\n" in v or "\r" in v:
        return "/"
    return v


def _set_cookie(resp: Response, s, sid: str) -> None:
    resp.set_cookie(s.effective_cookie_name, sid, max_age=s.session_absolute_ttl_seconds, httponly=True, secure=s.cookie_secure,
                    samesite="lax", path="/")


@router.get("/config")
async def config(state: Annotated[AppState, Depends(get_state)]):
    return {"mode": state.settings.auth_mode}


@router.get("/login")
async def login(request: Request, state: Annotated[AppState, Depends(get_state)], return_to: str | None = None,
                screen_hint: str | None = None, login_hint: str | None = None, reauth: bool = False):
    if state.oidc is None:
        raise Conflict("OIDC is not configured")
    await state.limiter.hit("auth_flow", f"ip:{client_ip(request, state.settings.trusted_proxy_hops)}")
    st, nonce = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
    verifier, challenge = pkce_pair()
    await state.redis.set(f"oidc:state:{st}", json.dumps({"nonce": nonce, "verifier": verifier, "return_to": safe_return_to(return_to)}), ex=600)
    extra: dict[str, str] = {}
    if screen_hint in ("signup", "login"):
        extra["screen_hint"] = screen_hint
    if login_hint and len(login_hint) < 320:
        extra["login_hint"] = login_hint
    if reauth:
        extra["prompt"] = "login"  # forces re-authentication (e.g. to satisfy MFA)
    try:
        url = await state.oidc.authorize_url(state=st, nonce=nonce, challenge=challenge, extra=extra)
    except Exception:  # noqa: BLE001
        raise Unavailable("Identity provider unavailable") from None
    return RedirectResponse(url, status_code=302)


def _fail(state: AppState, code: str) -> RedirectResponse:
    return RedirectResponse(f"{state.settings.public_base_url.rstrip('/')}/?auth_error={code}", status_code=302)


@router.get("/callback")
async def callback(request: Request, state: Annotated[AppState, Depends(get_state)], code: str | None = None,
                   st: str | None = None, error: str | None = None):
    s = state.settings
    ip = client_ip(request, s.trusted_proxy_hops)
    await state.limiter.hit("auth_flow", f"ip:{ip}")
    st = request.query_params.get("state")
    raw = await state.redis.getdel(f"oidc:state:{st}") if st else None  # atomic single use: replay of a state value fails
    if raw is None or error or not code:
        await metrics.incr(state.redis, "auth.login_failed")
        async with state.db.bare_session() as db:
            await audit.record(db, action="auth.login_failed", org_id=None, outcome="denied", ip=ip, reason=error or "bad_state")
        return _fail(state, "login_failed")
    saved = json.loads(raw)
    try:
        assert state.oidc is not None
        ts = await state.oidc.exchange_code(code, saved["verifier"])
        claims = await state.oidc.verify_id_token(ts.id_token, saved["nonce"])
    except OidcError as e:
        await metrics.incr(state.redis, "auth.login_failed")
        async with state.db.bare_session() as db:
            await audit.record(db, action="auth.login_failed", org_id=None, outcome="denied", ip=ip, reason=str(e)[:80])
        return _fail(state, "login_failed")
    except Exception:  # noqa: BLE001 - IdP unreachable
        return _fail(state, "idp_unavailable")
    sid, _ = await state.sessions.create(subject=claims.subject, email=claims.email, email_verified=claims.email_verified, name=claims.name,
                                         amr=list(claims.amr), refresh_token=ts.refresh_token, id_token=ts.id_token)
    async with state.db.bare_session() as db:
        await audit.record(db, action="auth.login", org_id=None, ip=ip, mfa=claims.mfa)
    resp = RedirectResponse(s.public_base_url.rstrip("/") + safe_return_to(saved["return_to"]), status_code=302)
    _set_cookie(resp, s, sid)
    return resp


@router.get("/session")
async def session(request: Request, state: Annotated[AppState, Depends(get_state)]):
    """Session restoration for the SPA. Returns the CSRF token the SPA must echo on unsafe requests."""
    sid = request.cookies.get(state.settings.effective_cookie_name)
    rec = await state.sessions.get(sid) if sid else None
    if rec is None:
        return JSONResponse({"authenticated": False}, status_code=200)
    return {"authenticated": True, "csrf": rec["csrf"], "idle_ttl_seconds": state.settings.session_idle_ttl_seconds}


@router.post("/logout")
async def logout(request: Request, state: Annotated[AppState, Depends(get_state)], ident: Annotated[Identity, Depends(get_identity)]):
    sid = getattr(request.state, "session_id", None)
    hint = None
    if sid:
        rec = await state.sessions.get(sid)
        hint = rec.get("id_token") if rec else None
        await state.sessions.delete(sid, ident.claims.subject)
    async with state.db.bare_session() as db:
        await audit.record(db, action="auth.logout", org_id=None, actor=ident.user.id, ip=ident.ip)
    url = await state.oidc.end_session_url(hint) if state.oidc else None
    resp = JSONResponse({"logout_url": url})
    resp.delete_cookie(state.settings.effective_cookie_name, path="/")
    return resp


@router.post("/logout-all")
async def logout_all(state: Annotated[AppState, Depends(get_state)], ident: Annotated[Identity, Depends(get_identity)]):
    n = await state.sessions.delete_all(ident.claims.subject)
    async with state.db.bare_session() as db:
        await audit.record(db, action="auth.logout_all", org_id=None, actor=ident.user.id, ip=ident.ip, sessions=n)
    return {"revoked": n}


