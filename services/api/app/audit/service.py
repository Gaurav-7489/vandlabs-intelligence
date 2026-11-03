"""Append-only audit trail. Never pass document contents or secrets in `meta`."""
import json
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import request_id_var


async def record(session: AsyncSession, *, action: str, org_id: UUID | None, actor: UUID | None = None,
                 resource_type: str | None = None, resource_id: Any = None, outcome: str = "success",
                 ip: str | None = None, **meta: Any) -> None:
    # Plain INSERT (no RETURNING): org-less security events are insertable but intentionally not readable by tenants,
    # and RETURNING would require SELECT-policy visibility of the new row.
    await session.execute(text(
        "INSERT INTO audit_events (org_id, actor_user_id, action, resource_type, resource_id, outcome, ip, request_id, metadata) "
        "VALUES (:org, :actor, :action, :rt, :rid, :outcome, :ip, :req, cast(:meta as jsonb))"),
        {"org": org_id, "actor": actor, "action": action, "rt": resource_type,
         "rid": str(resource_id) if resource_id is not None else None, "outcome": outcome, "ip": ip,
         "req": request_id_var.get(), "meta": json.dumps({k: v for k, v in meta.items() if v is not None}, default=str)})
