"""Opaque keyset (cursor) pagination over (created_at DESC, id DESC). Stable under concurrent inserts, index-friendly."""
import base64
import json
from datetime import datetime
from typing import Any, TypeVar
from uuid import UUID

from sqlalchemy import Select, and_, or_
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError

T = TypeVar("T")
MAX_LIMIT = 100


def encode(created_at: datetime, id_: UUID) -> str:
    return base64.urlsafe_b64encode(json.dumps([created_at.isoformat(), str(id_)]).encode()).decode()


def decode(cursor: str) -> tuple[datetime, UUID]:
    try:
        ts, id_ = json.loads(base64.urlsafe_b64decode(cursor.encode()))
        return datetime.fromisoformat(ts), UUID(id_)
    except Exception:  # noqa: BLE001
        raise AppError("Invalid cursor") from None


async def page(session: AsyncSession, stmt: Select[Any], model: Any, limit: int, cursor: str | None) -> dict[str, Any]:
    limit = max(1, min(limit, MAX_LIMIT))
    if cursor:
        c_ts, c_id = decode(cursor)
        stmt = stmt.where(or_(model.created_at < c_ts, and_(model.created_at == c_ts, model.id < c_id)))
    rows = list((await session.execute(stmt.order_by(model.created_at.desc(), model.id.desc()).limit(limit + 1))).scalars())
    more = len(rows) > limit
    rows = rows[:limit]
    return {"items": rows, "next_cursor": encode(rows[-1].created_at, rows[-1].id) if more and rows else None}
