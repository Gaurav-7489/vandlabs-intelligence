from datetime import UTC, date, datetime, timedelta
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Header
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.audit import service as audit
from app.core.errors import Conflict, Forbidden, NotFound
from app.core.pagination import page
from app.decisions import statemachine as sm
from app.identity.deps import Principal, require
from app.identity.permissions import P
from app.models import Approval, Decision, Execution, Insight, Outcome, Task

router = APIRouter(prefix="/decisions", tags=["decisions"])


class DecisionIn(BaseModel):
    insight_id: UUID
    action_title: str | None = Field(default=None, max_length=500)
    action_owner_email: str | None = Field(default=None, max_length=320)
    action_due_in_days: int = Field(default=2, ge=0, le=90)


class CommentIn(BaseModel):
    comment: str = Field(default="", max_length=2000)


class OutcomeIn(BaseModel):
    result: str = Field(pattern="^(improved|unchanged|worse|unknown)$")
    notes: str = Field(default="", max_length=4000)


def view(d: Decision) -> dict[str, Any]:
    return {"id": d.id, "insight_id": d.insight_id, "title": d.title, "business_question": d.business_question,
            "observation": d.observation, "evidence": d.evidence, "alternatives": d.alternatives,
            "recommended_action": d.recommended_action, "risks": d.risks, "success_criteria": d.success_criteria,
            "state": d.state, "requested_by": d.requested_by, "approver_user_id": d.approver_user_id, "version": d.version,
            "created_at": d.created_at, "updated_at": d.updated_at}


async def _load(p: Principal, did: UUID, lock: bool = False) -> Decision:
    stmt = select(Decision).where(Decision.id == did)
    d = (await p.session.execute(stmt.with_for_update() if lock else stmt)).scalar_one_or_none()
    if d is None:
        raise NotFound("Decision not found")
    return d


def _move(d: Decision, target: str) -> str:
    sm.check(d.state, target)
    before, d.state = d.state, target
    d.version += 1
    d.updated_at = datetime.now(UTC)
    return before


async def _log(p: Principal, d: Decision, action: str, **meta: Any) -> None:
    await audit.record(p.session, action=action, org_id=p.org_id, actor=p.user.id, resource_type="decision",
                       resource_id=d.id, ip=p.ip, state=d.state, **meta)


@router.post("", status_code=201)
async def create(body: DecisionIn, p: Annotated[Principal, Depends(require(P.DECISIONS_WRITE))]):
    ins = (await p.session.execute(select(Insight).where(Insight.id == body.insight_id))).scalar_one_or_none()
    if ins is None:
        raise NotFound("Insight not found")
    owner = next((e["facts"].get("owner") for e in ins.evidence if e["type"] == "task" and e["facts"].get("owner")), None)
    action = {"type": "create_task", "title": body.action_title or f"Follow up: {ins.title}", "owner_email": body.action_owner_email,
              "owner_name": owner, "due_in_days": body.action_due_in_days}
    d = Decision(
        org_id=p.org_id, insight_id=ins.id, title=ins.title, business_question="What should we do about this commitment risk?",
        observation=ins.summary, evidence=ins.evidence,
        alternatives=[{"option": "Take no action", "note": "Risk remains; outcome depends on the unresolved items in the evidence."},
                      {"option": "Create an internal follow-up task (recommended)", "note": ins.recommended_step}],
        recommended_action=action, risks=ins.uncertainty, success_criteria="Follow-up task completed and the commitment delivered by its due date.",
        requested_by=p.user.id)
    p.session.add(d)
    await p.session.flush()
    await _log(p, d, "decision.created", insight_id=str(ins.id))
    return view(d)


@router.get("")
async def list_decisions(p: Annotated[Principal, Depends(require(P.DECISIONS_READ))], state: str | None = None,
                         limit: int = 25, cursor: str | None = None):
    stmt = select(Decision)
    if state:
        stmt = stmt.where(Decision.state == state)
    r = await page(p.session, stmt, Decision, limit, cursor)
    return {"items": [view(d) for d in r["items"]], "next_cursor": r["next_cursor"]}


@router.get("/{did}")
async def get_decision(did: UUID, p: Annotated[Principal, Depends(require(P.DECISIONS_READ))]):
    d = await _load(p, did)
    approvals = (await p.session.execute(select(Approval).where(Approval.decision_id == did).order_by(Approval.created_at))).scalars().all()
    execs = (await p.session.execute(select(Execution).where(Execution.decision_id == did).order_by(Execution.created_at))).scalars().all()
    outs = (await p.session.execute(select(Outcome).where(Outcome.decision_id == did).order_by(Outcome.created_at))).scalars().all()
    return {**view(d),
            "approvals": [{"id": a.id, "actor_user_id": a.actor_user_id, "action": a.action, "comment": a.comment, "created_at": a.created_at} for a in approvals],
            "executions": [{"id": e.id, "action_type": e.action_type, "status": e.status, "verified": e.verified, "result": e.result,
                            "error": e.error, "created_at": e.created_at} for e in execs],
            "outcomes": [{"id": o.id, "result": o.result, "notes": o.notes, "recorded_by": o.recorded_by, "created_at": o.created_at} for o in outs]}


@router.post("/{did}/submit")
async def submit(did: UUID, p: Annotated[Principal, Depends(require(P.DECISIONS_WRITE))]):
    d = await _load(p, did, lock=True)
    before = _move(d, "awaiting_approval")
    await _log(p, d, "decision.submitted", before=before)
    return view(d)


async def _decide(p: Principal, did: UUID, action: str, target: str, comment: str) -> dict[str, Any]:
    d = await _load(p, did, lock=True)
    sm.check(d.state, target)
    if d.requested_by == p.user.id:  # separation of duties: you cannot approve/reject your own proposal
        raise Forbidden("The requester cannot decide on their own decision")
    before = _move(d, target)
    d.approver_user_id = p.user.id
    p.session.add(Approval(org_id=p.org_id, decision_id=d.id, actor_user_id=p.user.id, action=action, comment=comment))
    await _log(p, d, f"decision.{action}", before=before)
    return view(d)


@router.post("/{did}/approve")
async def approve(did: UUID, body: CommentIn, p: Annotated[Principal, Depends(require(P.DECISIONS_APPROVE))]):
    return await _decide(p, did, "approve", "approved", body.comment)


@router.post("/{did}/reject")
async def reject(did: UUID, body: CommentIn, p: Annotated[Principal, Depends(require(P.DECISIONS_APPROVE))]):
    return await _decide(p, did, "reject", "rejected", body.comment)


@router.post("/{did}/defer")
async def defer(did: UUID, body: CommentIn, p: Annotated[Principal, Depends(require(P.DECISIONS_APPROVE))]):
    return await _decide(p, did, "defer", "deferred", body.comment)


@router.post("/{did}/execute")
async def execute(did: UUID, p: Annotated[Principal, Depends(require(P.DECISIONS_EXECUTE))],
                  idempotency_key: Annotated[str | None, Header(max_length=100)] = None):
    """Runs the single supported, narrowly scoped action (`create_task`) and VERIFIES it by re-reading the created record.
    Retrying with the same Idempotency-Key never creates a second task."""
    d = await _load(p, did, lock=True)
    key = idempotency_key or f"decision:{d.id}:v{d.version}"
    existing = (await p.session.execute(select(Execution).where(Execution.idempotency_key == key))).scalar_one_or_none()
    if existing is not None:
        return {"decision": view(d), "execution": {"id": existing.id, "status": existing.status, "verified": existing.verified, "result": existing.result},
                "replayed": True}
    action = d.recommended_action
    if action.get("type") != "create_task":
        raise Conflict("Unsupported action type")
    _move(d, "in_execution")
    ex = Execution(org_id=p.org_id, decision_id=d.id, action_type="create_task", idempotency_key=key, status="running")
    p.session.add(ex)
    await p.session.flush()
    try:
        async with p.session.begin_nested():
            task = Task(org_id=p.org_id, title=action["title"], owner_name=action.get("owner_name"), owner_email=action.get("owner_email"),
                        due_date=date.today() + timedelta(days=int(action.get("due_in_days", 2))), status="todo", origin="execution",
                        decision_id=d.id, created_by=p.user.id)
            p.session.add(task)
            await p.session.flush()
            # Verification: authoritative re-read of the persisted record, compared with the intended action.
            check = (await p.session.execute(select(Task).where(Task.id == task.id, Task.decision_id == d.id,
                                                                Task.title == action["title"]))).scalar_one_or_none()
            if check is None:
                raise RuntimeError("verification failed: task not found after creation")
        ex.status, ex.verified, ex.result = "succeeded", True, {"task_id": str(task.id)}
        _move(d, "completed")
        await _log(p, d, "decision.executed", task_id=str(task.id), verified=True)
    except Exception as e:  # noqa: BLE001 - execution failure is recorded, decision returns to `approved` for retry/escalation
        ex.status, ex.verified, ex.error = "failed", False, str(e)[:500]
        _move(d, "approved")
        await _log(p, d, "decision.execution_failed", error=str(e)[:200])
    return {"decision": view(d), "execution": {"id": ex.id, "status": ex.status, "verified": ex.verified, "result": ex.result, "error": ex.error},
            "replayed": False}


@router.post("/{did}/outcome")
async def record_outcome(did: UUID, body: OutcomeIn, p: Annotated[Principal, Depends(require(P.DECISIONS_WRITE))]):
    d = await _load(p, did, lock=True)
    before = _move(d, "outcome_measured")
    p.session.add(Outcome(org_id=p.org_id, decision_id=d.id, recorded_by=p.user.id, result=body.result, notes=body.notes))
    await _log(p, d, "decision.outcome_recorded", before=before, result=body.result)
    return view(d)


@router.post("/{did}/close")
async def close(did: UUID, p: Annotated[Principal, Depends(require(P.DECISIONS_WRITE))]):
    d = await _load(p, did, lock=True)
    before = _move(d, "closed")
    await _log(p, d, "decision.closed", before=before)
    return view(d)


@router.post("/{did}/reopen")
async def reopen(did: UUID, p: Annotated[Principal, Depends(require(P.DECISIONS_WRITE))]):
    d = await _load(p, did, lock=True)
    before = _move(d, "reopened")
    await _log(p, d, "decision.reopened", before=before)
    return view(d)
