"""Verifies the runtime DB role cannot bypass Row-Level Security. Run at startup (fatal in staging/production) and on /readyz."""
from dataclasses import dataclass, field

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

TENANT_TABLES = ("memberships", "documents", "document_chunks", "commitments", "tasks", "insights", "decisions", "approvals",
                 "executions", "outcomes", "ai_usage", "jobs", "audit_events", "organizations", "users", "insight_explanations")


@dataclass
class DbSafety:
    role: str = ""
    problems: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.problems


async def check_role_safety(session: AsyncSession) -> DbSafety:
    r = DbSafety()
    row = (await session.execute(text("SELECT current_user, rolsuper, rolbypassrls FROM pg_roles WHERE rolname = current_user"))).one()
    r.role = row[0]
    if row[1]:
        r.problems.append("role is a superuser")
    if row[2]:
        r.problems.append("role has BYPASSRLS")
    # Role attributes are not inherited, but a member can `SET ROLE` to a privileged role (e.g. Neon's console-created
    # roles are members of `neon_superuser`). Any membership path to such a role is an RLS bypass.
    escalations = (await session.execute(text(
        "SELECT r.rolname FROM pg_roles r WHERE r.rolname <> current_user AND pg_has_role(current_user, r.oid, 'MEMBER') "
        "AND (r.rolsuper OR r.rolbypassrls OR r.rolname IN ('neon_superuser', 'pg_write_all_data', 'pg_read_all_data'))"))).scalars().all()
    if escalations:
        r.problems.append(f"role is a member of privileged role(s): {', '.join(sorted(escalations))}")
    owned = (await session.execute(text(
        "SELECT tablename FROM pg_tables WHERE schemaname='public' AND tableowner = current_user AND tablename = ANY(:t)"),
        {"t": list(TENANT_TABLES)})).scalars().all()
    if owned:
        r.problems.append(f"role owns tenant tables: {', '.join(sorted(owned))}")
    unforced = (await session.execute(text(
        "SELECT c.relname FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='public' AND c.relname = ANY(:t) "
        "AND NOT (c.relrowsecurity AND c.relforcerowsecurity)"), {"t": list(TENANT_TABLES)})).scalars().all()
    if unforced:
        r.problems.append(f"RLS not enabled+forced on: {', '.join(sorted(unforced))}")
    return r
