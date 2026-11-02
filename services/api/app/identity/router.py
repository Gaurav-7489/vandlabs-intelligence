from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import func, select

from app.audit import service as audit
from app.core.errors import Conflict, Forbidden, NotFound
from app.core.state import AppState, get_state
from app.identity.deps import Identity, Principal, get_identity, get_platform_admin, require
from app.identity.permissions import ROLE_PERMISSIONS, ROLES, P
from app.models import Membership, Organization, User

router = APIRouter(tags=["identity"])


class OrgCreate(BaseModel):
    name: str = Field(min_length=2, max_length=200)
    slug: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{1,78}$")
    owner_email: EmailStr


class InviteIn(BaseModel):
    email: EmailStr
    role: str
    department: str | None = Field(default=None, max_length=100)


class RoleIn(BaseModel):
    role: str


def _check_role(role: str) -> None:
    if role not in ROLES:
        raise Conflict("Unknown role", allowed=list(ROLES))


@router.get("/me")
async def me(ident: Annotated[Identity, Depends(get_identity)], state: Annotated[AppState, Depends(get_state)]):
    async with state.db.user_session(ident.user.id) as s:
        rows = (await s.execute(select(Membership, Organization).join(Organization, Organization.id == Membership.org_id)
                                .where(Membership.user_id == ident.user.id, Membership.status == "active"))).all()
    return {
        "user": {"id": ident.user.id, "email": ident.user.email, "display_name": ident.user.display_name,
                 "is_platform_admin": ident.user.is_platform_admin, "mfa": ident.claims.mfa},
        "memberships": [{"org_id": o.id, "org_name": o.name, "role": m.role,
                         "permissions": sorted(p.value for p in ROLE_PERMISSIONS[m.role])} for m, o in rows]}


@router.post("/platform/organizations", status_code=201)
async def provision_org(body: OrgCreate, ident: Annotated[Identity, Depends(get_platform_admin)], state: Annotated[AppState, Depends(get_state)]):
    """Platform admins provision tenants; this grants NO access to tenant content (content tables have no platform policy)."""
    async with state.db.platform_session() as s:
        if (await s.execute(select(Organization).where(Organization.slug == body.slug))).scalar_one_or_none():
            raise Conflict("Slug already in use")
        org = Organization(name=body.name, slug=body.slug)
        s.add(org)
        await s.flush()
        user = (await s.execute(select(User).where(User.email == body.owner_email.lower()))).scalar_one_or_none()
        if user is None:
            user = User(email=body.owner_email.lower())
            s.add(user)
            await s.flush()
        await s.execute(select(func.set_config("app.org_id", str(org.id), True)))
        s.add(Membership(org_id=org.id, user_id=user.id, role="owner"))
        await audit.record(s, action="platform.org_provisioned", org_id=org.id, actor=ident.user.id, resource_type="organization",
                           resource_id=org.id, ip=ident.ip)
    return {"id": org.id, "name": org.name, "slug": org.slug}


@router.get("/platform/organizations")
async def list_orgs(ident: Annotated[Identity, Depends(get_platform_admin)], state: Annotated[AppState, Depends(get_state)]):
    async with state.db.platform_session() as s:
        orgs = (await s.execute(select(Organization).order_by(Organization.created_at.desc()).limit(200))).scalars().all()
    return {"items": [{"id": o.id, "name": o.name, "slug": o.slug, "status": o.status, "created_at": o.created_at} for o in orgs]}


@router.get("/members")
async def list_members(p: Annotated[Principal, Depends(require(P.MEMBERS_READ))]):
    rows = (await p.session.execute(select(Membership, User).join(User, User.id == Membership.user_id)
                                    .order_by(Membership.created_at).limit(500))).all()
    return {"items": [{"id": m.id, "user_id": u.id, "email": u.email, "display_name": u.display_name, "role": m.role,
                       "department": m.department, "status": m.status, "pending": u.subject is None} for m, u in rows]}


async def _assert_can_grant(p: Principal, role: str) -> None:
    if role in ("owner", "admin") and p.role != "owner":
        raise Forbidden("Only an owner can grant owner or admin roles")


@router.post("/members", status_code=201)
async def invite_member(body: InviteIn, p: Annotated[Principal, Depends(require(P.MEMBERS_WRITE))]):
    _check_role(body.role)
    await _assert_can_grant(p, body.role)
    email = body.email.lower()
    user = (await p.session.execute(select(User).where(User.email == email))).scalar_one_or_none()
    if user is None:
        user = User(email=email)
        p.session.add(user)
        await p.session.flush()
    if (await p.session.execute(select(Membership).where(Membership.user_id == user.id))).scalar_one_or_none():
        raise Conflict("User is already a member")
    m = Membership(org_id=p.org_id, user_id=user.id, role=body.role, department=body.department)
    p.session.add(m)
    await p.session.flush()
    await audit.record(p.session, action="member.invited", org_id=p.org_id, actor=p.user.id, resource_type="membership",
                       resource_id=m.id, ip=p.ip, role=body.role)
    return {"id": m.id, "email": email, "role": m.role}


@router.patch("/members/{member_id}")
async def change_role(member_id: UUID, body: RoleIn, p: Annotated[Principal, Depends(require(P.MEMBERS_WRITE))]):
    _check_role(body.role)
    await _assert_can_grant(p, body.role)
    m = (await p.session.execute(select(Membership).where(Membership.id == member_id).with_for_update())).scalar_one_or_none()
    if m is None:
        raise NotFound("Member not found")
    if m.role in ("owner", "admin") and p.role != "owner":
        raise Forbidden("Only an owner can modify owners or admins")
    if m.role == "owner" and body.role != "owner":
        owners = (await p.session.execute(select(func.count()).select_from(Membership).where(Membership.role == "owner", Membership.status == "active"))).scalar_one()
        if owners <= 1:
            raise Conflict("An organization must keep at least one owner")
    before, m.role = m.role, body.role
    await audit.record(p.session, action="member.role_changed", org_id=p.org_id, actor=p.user.id, resource_type="membership",
                       resource_id=m.id, ip=p.ip, before=before, after=body.role)
    return {"id": m.id, "role": m.role}


@router.delete("/members/{member_id}", status_code=204)
async def deactivate_member(member_id: UUID, p: Annotated[Principal, Depends(require(P.MEMBERS_WRITE))]):
    m = (await p.session.execute(select(Membership).where(Membership.id == member_id).with_for_update())).scalar_one_or_none()
    if m is None:
        raise NotFound("Member not found")
    if m.role in ("owner", "admin") and p.role != "owner":
        raise Forbidden("Only an owner can remove owners or admins")
    if m.role == "owner":
        owners = (await p.session.execute(select(func.count()).select_from(Membership).where(Membership.role == "owner", Membership.status == "active"))).scalar_one()
        if owners <= 1:
            raise Conflict("An organization must keep at least one owner")
    m.status = "deactivated"
    await audit.record(p.session, action="member.deactivated", org_id=p.org_id, actor=p.user.id, resource_type="membership", resource_id=m.id, ip=p.ip)


