from typing import Annotated

from fastapi import APIRouter, Depends, Request
from sqlalchemy import func, select

from app.ai.gateway import estimate_cost
from app.core.state import get_state
from app.identity.deps import Principal, require
from app.identity.permissions import P
from app.models import AiUsage, AuditEvent

router = APIRouter(tags=["audit"])


@router.get("/audit")
async def list_audit(p: Annotated[Principal, Depends(require(P.AUDIT_READ))], limit: int = 50, before_id: int | None = None,
                     action: str | None = None):
    stmt = select(AuditEvent)
    if before_id:
        stmt = stmt.where(AuditEvent.id < before_id)
    if action:
        stmt = stmt.where(AuditEvent.action == action)
    rows = (await p.session.execute(stmt.order_by(AuditEvent.id.desc()).limit(max(1, min(limit, 200))))).scalars().all()
    return {"items": [{"id": e.id, "action": e.action, "actor_user_id": e.actor_user_id, "resource_type": e.resource_type,
                       "resource_id": e.resource_id, "outcome": e.outcome, "request_id": e.request_id, "metadata": e.meta,
                       "created_at": e.created_at} for e in rows],
            "next_before_id": rows[-1].id if len(rows) == limit else None}


@router.get("/usage/ai")
async def ai_usage(request: Request, p: Annotated[Principal, Depends(require(P.USAGE_READ))]):
    pricing = get_state(request).ai.pricing
    rows = (await p.session.execute(select(AiUsage.provider, AiUsage.model, AiUsage.task, AiUsage.status, func.count(),
                                           func.coalesce(func.sum(AiUsage.input_tokens), 0), func.coalesce(func.sum(AiUsage.output_tokens), 0))
                                    .where(AiUsage.created_at >= func.date_trunc("day", func.now()))
                                    .group_by(AiUsage.provider, AiUsage.model, AiUsage.task, AiUsage.status))).all()
    return {"period": "today", "items": [{"provider": r[0], "model": r[1], "task": r[2], "status": r[3], "calls": r[4],
                                          "input_tokens": r[5], "output_tokens": r[6],
                                          "cost_usd": estimate_cost(pricing, r[1], int(r[5]), int(r[6])),  # null = no configured price
                                          "pricing": ({"effective_date": pricing[r[1]].effective_date, "source": pricing[r[1]].source} if r[1] in pricing else None)}
                                         for r in rows]}
