"""Server-side identity + tenant resolution. The browser supplies only a bearer token and a *requested* org id;
role and membership are always loaded from the database."""
import hmac
from dataclasses import dataclass
from typing import Annotated, Any
from uuid import UUID

from fastapi import Depends, Header, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit import service as audit
from app.core import metrics
from app.core.errors import Forbidden, Unauthorized
from app.core.state import AppState, get_state
from app.identity.permissions import PRIVILEGED_ROLES, ROLE_PERMISSIONS, P
from app.identity.tokens import Claims
from app.models import Membership, User


def client_ip(request: Request, hops: int) -> str | None:
    if getattr(request.state, "edge_trusted", False):  # these headers are spoofable unless the edge authenticated itself
        fwd = request.headers.get("x-vand-client-ip") or request.headers.get("cf-connecting-ip") or ""
        if fwd:
            return fwd.strip()
    parts = [p.strip() for p in request.headers.get("x-forwarded-for", "").split(",") if p.strip()]
    if parts and hops > 0:
        return parts[max(0, len(parts) - hops)]
    return request.client.host if request.client else None


@dataclass
class Identity:
    user: User
    claims: Claims
    ip: str | None


@dataclass
class Principal:
    user: User
    org_id: UUID
    role: str
    session: AsyncSession
    ip: str | None

    def can(self, perm: P) -> bool:
        return perm in ROLE_PERMISSIONS.get(self.role, frozenset())

    def require(self, perm: P) -> None:
        if not self.can(perm):
            raise Forbidden("You do not have permission to perform this action")


UNSAFE = {"POST", "PUT", "PATCH", "DELETE"}


def _check_csrf(request: Request, state: AppState, rec: dict[str, Any]) -> None:
    """Cookie-authenticated unsafe requests need BOTH an allowed Origin and the per-session CSRF token. (CORS is not CSRF protection.)"""
    origin = request.headers.get("origin", "").rstrip("/")
    token = request.headers.get("x-csrf-token", "")
    if origin not in state.settings.allowed_origins or not hmac.compare_digest(token, rec["csrf"]):
        raise Forbidden("CSRF validation failed")


async def _claims_from_request(request: Request, state: AppState) -> tuple[Claims, dict[str, Any] | None]:
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        tok = auth[7:].strip()
        if state.settings.auth_mode == "dev":
            return state.verifier.verify(tok), None
        assert state.oidc is not None
        return await state.oidc.verify_access_jwt(tok), None
    sid = request.cookies.get(state.settings.effective_cookie_name)
    if sid and state.settings.auth_mode == "oidc":
        rec = await state.sessions.get(sid)
        if rec is not None:
            if request.method in UNSAFE:
                _check_csrf(request, state, rec)
            request.state.session_id = sid
            return Claims(subject=rec["sub"], email=rec["email"], email_verified=rec["email_verified"], name=rec["name"], amr=tuple(rec["amr"])), rec
    raise Unauthorized("Authentication required")


async def get_identity(request: Request, state: Annotated[AppState, Depends(get_state)]) -> Identity:
    ip = client_ip(request, state.settings.trusted_proxy_hops)
    try:
        claims, _rec = await _claims_from_request(request, state)
    except Unauthorized:
        await metrics.incr(state.redis, "auth.failure")
        await state.limiter.hit("auth_failure", f"ip:{ip}")
        async with state.db.bare_session() as s:
            await audit.record(s, action="auth.token_rejected", org_id=None, outcome="denied", ip=ip)
        raise
    async with state.db.identity_session() as s:
        user = (await s.execute(select(User).where(User.subject == claims.subject))).scalar_one_or_none()
        if user is None and claims.email and claims.email_verified:
            # Bind an invited (subject-less) user to this identity only when the IdP asserts a verified email.
            user = (await s.execute(select(User).where(User.email == claims.email, User.subject.is_(None)))).scalar_one_or_none()
            if user is not None:
                user.subject = claims.subject
                user.display_name = user.display_name or claims.name
        if user is None:
            if not claims.email:
                raise Unauthorized("Token has no email claim")
            existing = (await s.execute(select(User).where(User.email == claims.email))).scalar_one_or_none()
            if existing is not None:  # email already owned by another subject: never merge identities
                raise Unauthorized("Account conflict")
            user = User(subject=claims.subject, email=claims.email, display_name=claims.name)
            s.add(user)
        await s.flush()  # persist the subject binding BEFORE detaching the object
        s.expunge(user)
    await state.limiter.hit("read" if request.method in ("GET", "HEAD") else "write", f"user:{user.id}")
    return Identity(user=user, claims=claims, ip=ip)


async def get_platform_admin(ident: Annotated[Identity, Depends(get_identity)],
                             state: Annotated[AppState, Depends(get_state)]) -> Identity:
    if not ident.user.is_platform_admin:
        raise Forbidden("Platform administrator required")
    if state.settings.require_mfa_for_privileged and not ident.claims.mfa:
        raise Forbidden("Multi-factor authentication required", reason="mfa_required")
    return ident


async def get_principal(
    request: Request,
    ident: Annotated[Identity, Depends(get_identity)],
    state: Annotated[AppState, Depends(get_state)],
    x_org_id: Annotated[str | None, Header()] = None,
):
    """Yields a Principal whose DB session is already bound to the validated tenant (RLS context)."""
    if not x_org_id:
        raise Forbidden("X-Org-ID header required")
    try:
        org_id = UUID(x_org_id)
    except ValueError:
        raise Forbidden("Invalid organization") from None
    denial: tuple[str, str, str | None] | None = None
    async with state.db.tenant_session(org_id) as session:
        m = (await session.execute(select(Membership).where(
            Membership.org_id == org_id, Membership.user_id == ident.user.id, Membership.status == "active"))).scalar_one_or_none()
        if m is None:
            denial = ("authz.org_denied", "You are not a member of this organization", None)
        elif state.settings.require_mfa_for_privileged and m.role in PRIVILEGED_ROLES and not ident.claims.mfa:
            denial = ("authz.mfa_required", "Multi-factor authentication required for this role", "mfa_required")
        else:
            request.state.org_id = org_id
            await state.limiter.hit("org_read", f"org:{org_id}")  # tenant-wide fairness quota across all of its users
            yield Principal(user=ident.user, org_id=org_id, role=m.role, session=session, ip=ident.ip)
    if denial:
        # Recorded in its own transaction (the tenant tx above is read-only). Same message for "no such org"
        # and "not a member": no tenant enumeration.
        async with state.db.bare_session() as s:
            await audit.record(s, action=denial[0], org_id=None, actor=ident.user.id, outcome="denied", ip=ident.ip, requested_org=str(org_id))
        extra: dict[str, Any] = {"reason": denial[2]} if denial[2] else {}
        raise Forbidden(denial[1], **extra)


def require(perm: P):
    """Dependency factory: resolves the Principal and enforces a permission before the handler runs."""
    async def _dep(principal: Annotated[Principal, Depends(get_principal)]) -> Principal:
        principal.require(perm)
        return principal
    return _dep

