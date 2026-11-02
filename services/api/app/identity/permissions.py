"""Role templates -> permission sets. Enforced server-side only; the browser never supplies roles."""
from enum import StrEnum


class P(StrEnum):
    ORG_READ = "org.read"
    ORG_ADMIN = "org.admin"
    MEMBERS_READ = "members.read"
    MEMBERS_WRITE = "members.write"
    DOCS_READ = "documents.read"
    DOCS_WRITE = "documents.write"
    DOCS_DELETE = "documents.delete"
    SEARCH = "search.read"
    INSIGHTS_READ = "insights.read"
    INSIGHTS_WRITE = "insights.write"
    DECISIONS_READ = "decisions.read"
    DECISIONS_WRITE = "decisions.write"
    DECISIONS_APPROVE = "decisions.approve"
    DECISIONS_EXECUTE = "decisions.execute"
    TASKS_READ = "tasks.read"
    TASKS_WRITE = "tasks.write"
    AI_ASK = "ai.ask"
    AUDIT_READ = "audit.read"
    USAGE_READ = "usage.read"


_READ = {P.ORG_READ, P.DOCS_READ, P.SEARCH, P.INSIGHTS_READ, P.DECISIONS_READ, P.TASKS_READ}

ROLE_PERMISSIONS: dict[str, frozenset[P]] = {
    "owner": frozenset(P),
    "admin": frozenset(P),
    "manager": frozenset(_READ | {P.DOCS_WRITE, P.DOCS_DELETE, P.INSIGHTS_WRITE, P.DECISIONS_WRITE, P.DECISIONS_APPROVE,
                                  P.DECISIONS_EXECUTE, P.TASKS_WRITE, P.AI_ASK, P.MEMBERS_READ, P.USAGE_READ}),
    "staff": frozenset(_READ | {P.DOCS_WRITE, P.TASKS_WRITE, P.AI_ASK}),
    "viewer": frozenset(_READ),
    "auditor": frozenset(_READ | {P.AUDIT_READ, P.MEMBERS_READ, P.USAGE_READ}),
}
PRIVILEGED_ROLES = frozenset({"owner", "admin"})
ROLES = tuple(ROLE_PERMISSIONS)
