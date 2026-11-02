from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select

from app.audit import service as audit
from app.core.errors import NotFound
from app.core.pagination import page
from app.identity.deps import Principal, require
from app.identity.permissions import P
from app.models import Task

router = APIRouter(prefix="/tasks", tags=["tasks"])


def view(t: Task) -> dict:
    return {"id": t.id, "title": t.title, "owner_name": t.owner_name, "owner_email": t.owner_email, "due_date": t.due_date,
            "status": t.status, "origin": t.origin, "decision_id": t.decision_id, "source_locator": t.source_locator, "created_at": t.created_at}


@router.get("")
async def list_tasks(p: Annotated[Principal, Depends(require(P.TASKS_READ))], status: str | None = None, origin: str | None = None,
                     limit: int = 25, cursor: str | None = None):
    stmt = select(Task)
    if status:
        stmt = stmt.where(Task.status == status)
    if origin:
        stmt = stmt.where(Task.origin == origin)
    r = await page(p.session, stmt, Task, limit, cursor)
    return {"items": [view(t) for t in r["items"]], "next_cursor": r["next_cursor"]}


class TaskStatusIn(BaseModel):
    status: Literal["todo", "in_progress", "blocked", "done"]


@router.patch("/{tid}")
async def update_status(tid: UUID, body: TaskStatusIn, p: Annotated[Principal, Depends(require(P.TASKS_WRITE))]):
    t = (await p.session.execute(select(Task).where(Task.id == tid))).scalar_one_or_none()
    if t is None:
        raise NotFound("Task not found")
    before, t.status = t.status, body.status
    await audit.record(p.session, action="task.status_changed", org_id=p.org_id, actor=p.user.id, resource_type="task",
                       resource_id=t.id, ip=p.ip, before=before, after=body.status)
    return view(t)
