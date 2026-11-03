"""Durable Postgres-backed job queue (SELECT ... FOR UPDATE SKIP LOCKED).

Chosen over an external broker for the first release: jobs are transactional with business writes (no dual-write
loss), retries/dead-letter are queryable, and there is one less service to operate. See ADR-0003.
"""
import json
from datetime import timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.errors import RateLimited
from app.models import Job

STALE_LOCK = timedelta(minutes=10)


async def enqueue(session: AsyncSession, *, org_id: UUID, kind: str, payload: dict[str, Any],
                  idempotency_key: str | None = None, max_attempts: int = 4, max_queued: int | None = None) -> Job:
    if idempotency_key:
        existing = (await session.execute(select(Job).where(Job.org_id == org_id, Job.idempotency_key == idempotency_key))).scalar_one_or_none()
        if existing:
            return existing
    queued = (await session.execute(select(func.count()).select_from(Job).where(Job.status.in_(["queued", "retry_scheduled"])))).scalar_one()
    if queued >= (max_queued if max_queued is not None else get_settings().max_queued_jobs_per_org):
        raise RateLimited("Too many queued jobs for this organization; try again shortly", headers={"Retry-After": "30"})
    job = Job(org_id=org_id, kind=kind, payload=payload, idempotency_key=idempotency_key, max_attempts=max_attempts)
    session.add(job)
    await session.flush()
    return job


async def claim(session: AsyncSession, worker_id: str) -> Job | None:
    """Claims one runnable job. Also reclaims jobs whose worker died mid-run (stale lock) - they are NOT marked
    successful; they simply run again (handlers are idempotent) until max_attempts, then dead-letter."""
    row = (await session.execute(text("""
        SELECT id FROM jobs
        WHERE (status IN ('queued','retry_scheduled') AND run_at <= now())
           OR (status = 'running' AND locked_at < now() - make_interval(secs => :stale))
        ORDER BY run_at, created_at
        FOR UPDATE SKIP LOCKED LIMIT 1"""), {"stale": STALE_LOCK.total_seconds()})).first()
    if row is None:
        return None
    job = (await session.execute(select(Job).where(Job.id == row[0]))).scalar_one()
    job.attempts += 1
    job.status = "running"
    job.locked_at = func.now()
    job.locked_by = worker_id
    await session.flush()
    await session.refresh(job)
    return job


async def complete(session: AsyncSession, job_id: UUID, result: dict[str, Any]) -> None:
    await session.execute(text("UPDATE jobs SET status='completed', result=cast(:r as jsonb), locked_at=NULL, updated_at=now() WHERE id=:id"),
                          {"id": job_id, "r": json.dumps(result)})


async def fail(session: AsyncSession, job_id: UUID, error: str) -> str:
    """Retry with exponential backoff, else dead-letter. Returns the new status."""
    r = (await session.execute(text("""
        UPDATE jobs SET
          status = CASE WHEN attempts >= max_attempts THEN 'dead_letter' ELSE 'retry_scheduled' END,
          run_at = now() + make_interval(secs => least(300, power(2, attempts) * 5)),
          last_error = :e, locked_at = NULL, updated_at = now()
        WHERE id = :id RETURNING status"""), {"id": job_id, "e": error[:2000]})).scalar_one()
    return str(r)


async def wake_worker(redis: Any) -> None:
    """Tell an idle worker there is work (it blocks on Redis instead of polling Postgres). Best effort: the worker's
    periodic sweep still finds the job if this signal is lost."""
    try:
        pipe = redis.pipeline()
        pipe.rpush("jobs:wake", "1")
        pipe.ltrim("jobs:wake", -10, -1)
        pipe.expire("jobs:wake", 3600)
        await pipe.execute()
    except Exception:  # noqa: BLE001
        return
