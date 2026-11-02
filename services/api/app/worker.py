"""Background worker: claims durable jobs, runs tenant-scoped handlers, retries with backoff, dead-letters on exhaustion.

Run: python -m app.worker
"""
import asyncio
import os
import signal
import socket
from typing import Any
from uuid import UUID

from app.core.config import get_settings
from app.core.db import Database, make_engine
from app.core.logging import configure_logging, get_logger
from app.core.storage import make_storage
from app.ingestion.pipeline import ingest_document
from app.intelligence.service import run_analysis
from app.jobs import queue

log = get_logger("worker")


class Worker:
    def __init__(self, db: Database | None = None):
        self.s = get_settings()
        self.db = db or Database(make_engine(self.s.worker_database_url, self.s))
        self.storage = make_storage(self.s)
        self.id = f"{socket.gethostname()}:{os.getpid()}"
        self._stop = asyncio.Event()

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
        except Exception as e:  # noqa: BLE001 - never crash the loop on a job error
            log.error("job_failed", extra={"job_id": str(job_id), "kind": kind, "err": type(e).__name__})
            async with self.db.bare_session() as s:
                status = await queue.fail(s, job_id, f"{type(e).__name__}: {e}")
            log.warning("job_status", extra={"job_id": str(job_id), "status": status})
        return True

    async def _dispatch(self, session: Any, org_id: UUID, kind: str, payload: dict[str, Any]) -> dict[str, Any]:
        if kind == "ingest_document":
            return await ingest_document(session, self.storage, self.s, org_id, UUID(payload["document_id"]))
        if kind == "analyze":
            return await run_analysis(session, self.s, org_id)
        raise ValueError(f"unknown job kind {kind}")

    async def run_forever(self, poll: float = 1.0) -> None:
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, self._stop.set)
        log.info("worker_started", extra={"worker": self.id})
        while not self._stop.is_set():
            if not await self.run_one():
                try:
                    await asyncio.wait_for(self._stop.wait(), timeout=poll)
                except TimeoutError:
                    pass
        await self.db.dispose()
        log.info("worker_stopped")


async def _set_job_tenant_result(session: Any, job_id: UUID, result: dict[str, Any]) -> None:
    await queue.complete(session, job_id, result)


def main() -> None:
    configure_logging()
    asyncio.run(Worker().run_forever())


if __name__ == "__main__":
    main()
