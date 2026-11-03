"""Background worker: claims durable jobs, runs tenant-scoped handlers, retries with backoff, dead-letters on exhaustion.

Run: python -m app.worker
"""
import asyncio
import os
import signal
import socket
import time
from typing import Any
from uuid import UUID

import redis.asyncio as aioredis
from sqlalchemy import text, update

from app.core import metrics
from app.core.config import get_settings
from app.core.db import Database, make_engine
from app.core.dbsafety import check_role_safety
from app.core.logging import configure_logging, get_logger
from app.core.storage import make_storage
from app.ingestion.pipeline import HoldForRetry, ingest_document
from app.ingestion.scan import make_scanner
from app.intelligence.service import run_analysis
from app.jobs import queue
from app.models import Document

log = get_logger("worker")


class Worker:
    def __init__(self, db: Database | None = None):
        self.s = get_settings()
        self.db = db or Database(make_engine(self.s.worker_database_url, self.s))
        self.storage = make_storage(self.s)
        self.scanner = make_scanner(self.s)
        self.id = f"{socket.gethostname()}:{os.getpid()}"
        self.redis = aioredis.from_url(self.s.redis_url, decode_responses=True, socket_timeout=1.0, socket_connect_timeout=1.0)
        self._stop = asyncio.Event()

    async def publish_stats(self) -> None:
        """Queue depth/age by status, from the worker role (the only role with cross-tenant visibility on `jobs`)."""
        try:
            async with self.db.bare_session() as s:
                rows = (await s.execute(text("SELECT status, count(*), coalesce(extract(epoch FROM now() - min(run_at)), 0) FROM jobs GROUP BY status"))).all()
            by = {r[0]: int(r[1]) for r in rows}
            oldest = max((float(r[2]) for r in rows if r[0] in ("queued", "retry_scheduled")), default=0.0)
            await metrics.publish_queue_snapshot(self.redis, {"by_status": by, "queued_oldest_age_seconds": round(oldest, 1),
                                                              "dead_letter": by.get("dead_letter", 0)})
        except Exception as exc:  # noqa: BLE001
            log.warning("stats_publish_failed", extra={"err": type(exc).__name__})

    async def run_one(self) -> bool:
        """Claim and execute one job. Returns False when the queue is empty."""
        async with self.db.bare_session() as s:
            job = await queue.claim(s, self.id)
            if job is None:
                return False
            job_id, org_id, kind, payload = job.id, job.org_id, job.kind, dict(job.payload)
        try:
            # Handler work and its result share ONE tenant transaction: partial effects never commit on failure.
            async with self.db.tenant_session(org_id) as session:
                result = await self._dispatch(session, org_id, kind, payload)
                await _set_job_tenant_result(session, job_id, result)
            log.info("job_completed", extra={"job_id": str(job_id), "kind": kind})
            await metrics.incr(self.redis, "jobs.completed")
            if result.get("status") in ("failed", "quarantined"):
                await metrics.incr(self.redis, f"documents.{result['status']}")
        except HoldForRetry as h:
            async with self.db.tenant_session(org_id) as session:  # persist the visible hold state (handler tx was rolled back)
                await session.execute(update(Document).where(Document.id == h.document_id).values(**h.fields))
            async with self.db.bare_session() as s:
                status = await queue.fail(s, job_id, "held: security scan unavailable")
            log.warning("job_held", extra={"job_id": str(job_id), "status": status})
            await metrics.incr(self.redis, "scan.unavailable")
        except Exception as e:  # noqa: BLE001 - never crash the loop on a job error
            log.error("job_failed", extra={"job_id": str(job_id), "kind": kind, "err": type(e).__name__})
            async with self.db.bare_session() as s:
                status = await queue.fail(s, job_id, f"{type(e).__name__}: {e}")
            await metrics.incr(self.redis, "jobs.failed")
            if status == "dead_letter":
                await metrics.incr(self.redis, "jobs.dead_letter")
            log.warning("job_status", extra={"job_id": str(job_id), "status": status})
        return True

    async def _dispatch(self, session: Any, org_id: UUID, kind: str, payload: dict[str, Any]) -> dict[str, Any]:
        if kind == "ingest_document":
            return await ingest_document(session, self.storage, self.scanner, self.s, org_id, UUID(payload["document_id"]))
        if kind == "analyze":
            return await run_analysis(session, self.s, org_id)
        raise ValueError(f"unknown job kind {kind}")

    async def run_forever(self, poll: float = 1.0) -> None:
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, self._stop.set)
        if self.s.env in ("staging", "production"):
            async with self.db.bare_session() as probe:
                safety = await check_role_safety(probe)
            if not safety.ok:
                raise RuntimeError("Unsafe database role configuration: " + "; ".join(safety.problems))
        log.info("worker_started", extra={"worker": self.id})
        last_pub = 0.0
        while not self._stop.is_set():
            if time.monotonic() - last_pub > 30:
                await self.publish_stats()
                last_pub = time.monotonic()
            if not await self.run_one():
                try:
                    await asyncio.wait_for(self._stop.wait(), timeout=poll)
                except TimeoutError:
                    pass
        await self.db.dispose()
        await self.redis.aclose()
        log.info("worker_stopped")


async def _set_job_tenant_result(session: Any, job_id: UUID, result: dict[str, Any]) -> None:
    await queue.complete(session, job_id, result)


def main() -> None:
    configure_logging()
    asyncio.run(Worker().run_forever())


if __name__ == "__main__":
    main()
