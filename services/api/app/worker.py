"""Background worker: claims durable jobs, runs tenant-scoped handlers, retries with backoff, dead-letters on exhaustion.

Run: python -m app.worker
"""
import asyncio
import contextlib
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
WAKE_KEY = "jobs:wake"


class Worker:
    def __init__(self, db: Database | None = None):
        self.s = get_settings()
        self.db = db or Database(make_engine(self.s.worker_database_url, self.s))
        self.storage = make_storage(self.s)
        self.scanner = make_scanner(self.s)
        self.id = f"{socket.gethostname()}:{os.getpid()}"
        self.redis = aioredis.from_url(self.s.redis_url, decode_responses=True, socket_timeout=1.0, socket_connect_timeout=1.0)
        # Blocking reads (BLPOP) need their own connection WITHOUT a short socket timeout: if the client gave up after 1 s while
        # the server-side BLPOP was still pending, the next wake signal would be delivered to the abandoned request and lost.
        self.redis_block = aioredis.from_url(self.s.redis_url, decode_responses=True, socket_timeout=None, socket_connect_timeout=2.0)
        self._stop = asyncio.Event()
        self._holds_pending = False

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
                status = await queue.hold(s, job_id, "security scan unavailable", self.s.scan_hold_retry_seconds, self.s.scan_hold_max_seconds)
            self._holds_pending = status == "retry_scheduled" or self._holds_pending
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

    async def heartbeat(self) -> None:
        """Redis-only liveness signal (does NOT touch Postgres, so an idle Neon compute can scale to zero)."""
        await self.redis.set(metrics.HEARTBEAT_KEY, str(time.time()), ex=600)

    async def next_due_seconds(self) -> float:
        """Seconds until the earliest scheduled job (retry backoff) - asked only while the DB is already awake."""
        async with self.db.bare_session() as s:
            v = (await s.execute(text("SELECT extract(epoch FROM min(run_at) - now()) FROM jobs WHERE status IN ('queued','retry_scheduled')"))).scalar_one()
        return max(0.0, float(v)) if v is not None else float("inf")

    async def release_holds_if_scanner_back(self) -> bool:
        """While uploads are held for a missing scanner, PING clamd (no DB). On PONG, release the holds (one DB write)."""
        if not self._holds_pending or not await self.scanner.ping():
            return False
        async with self.db.bare_session() as s:
            n = await queue.release_holds(s)
        self._holds_pending = False
        log.info("scan_holds_released", extra={"jobs": n})
        return n > 0

    async def wait_for_work(self, max_wait: float) -> bool:
        """Block on the Redis wake list (no DB polling). Heartbeat every 30 s. Returns True if woken by a signal
        or because scanner-held jobs were released."""
        deadline = time.monotonic() + max_wait
        while not self._stop.is_set() and time.monotonic() < deadline:
            await self.heartbeat()
            if await self.release_holds_if_scanner_back():
                return True
            cap = float(self.s.scan_probe_seconds) if self._holds_pending else 30.0
            slice_s = max(1, int(min(30.0, cap, deadline - time.monotonic())))
            try:
                if await self._blpop_or_stop(slice_s):
                    return True
            except Exception as exc:  # noqa: BLE001
                # Redis unavailable: degrade to checking Postgres directly (keeps jobs moving; may keep a serverless DB awake).
                log.warning("wake_wait_failed", extra={"err": type(exc).__name__})
                await asyncio.sleep(min(5.0, slice_s))
                return True
        return False

    async def _blpop_or_stop(self, timeout_s: int) -> bool:
        """BLPOP that a shutdown signal interrupts at once (otherwise SIGTERM waits up to 30 s and platforms SIGKILL us).
        The blocking connection is only abandoned on shutdown, so a wake signal can never be swallowed while running;
        a signal popped during shutdown is harmless because jobs are durable in Postgres and the next worker drains them."""
        pop = asyncio.ensure_future(self.redis_block.blpop([WAKE_KEY], timeout=timeout_s))
        stop = asyncio.ensure_future(self._stop.wait())
        try:
            done, _ = await asyncio.wait({pop, stop}, return_when=asyncio.FIRST_COMPLETED)
        finally:
            stop.cancel()
        if pop in done:
            return bool(pop.result())
        pop.cancel()
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await pop
        return False

    async def drain(self, grace_s: float = 5.0) -> int:
        """Run jobs until the queue is empty. After a wake signal the enqueuing transaction may not have committed yet,
        so keep trying briefly before going idle."""
        n, deadline = 0, time.monotonic() + grace_s
        while not self._stop.is_set():
            if await self.run_one():
                n, deadline = n + 1, time.monotonic() + grace_s
                continue
            if n or time.monotonic() >= deadline:
                break
            await asyncio.sleep(0.5)
        return n

    async def run_forever(self) -> None:
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, self._stop.set)
        if self.s.env in ("staging", "production"):
            async with self.db.bare_session() as probe:
                safety = await check_role_safety(probe)
            if not safety.ok:
                raise RuntimeError("Unsafe database role configuration: " + "; ".join(safety.problems))
        async with self.db.bare_session() as s:  # holds from before a restart are still released when the scanner returns
            self._holds_pending = await queue.count_holds(s) > 0
        log.info("worker_started", extra={"worker": self.id, "idle_sweep_s": self.s.worker_idle_sweep_seconds})
        while not self._stop.is_set():
            # DB touched only here: on a wake signal, a due retry, or the periodic safety sweep (stale locks).
            await self.drain(grace_s=0.0)
            await self.publish_stats()
            wait = min(self.s.worker_idle_sweep_seconds, await self.next_due_seconds())
            if await self.wait_for_work(wait):
                await self.drain()
        await self.db.dispose()
        await self.redis.aclose()
        await self.redis_block.aclose()
        log.info("worker_stopped")


async def _set_job_tenant_result(session: Any, job_id: UUID, result: dict[str, Any]) -> None:
    await queue.complete(session, job_id, result)


def main() -> None:
    configure_logging()
    asyncio.run(Worker().run_forever())


if __name__ == "__main__":
    main()
