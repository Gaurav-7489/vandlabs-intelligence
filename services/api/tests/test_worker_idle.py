"""The idle worker must not keep a serverless Postgres (Neon Free scales to zero after 5 idle minutes) awake."""
import asyncio
import time
import uuid
from contextlib import asynccontextmanager

from sqlalchemy import text

from app.core import metrics
from app.core.config import get_settings
from app.core.db import Database, make_engine
from app.worker import Worker
from tests.conftest import drain

API = "/api/v1"


class CountingDb(Database):
    def __init__(self, engine):
        super().__init__(engine)
        self.opens = 0

    @asynccontextmanager
    async def bare_session(self):
        self.opens += 1
        async with super().bare_session() as s:
            yield s

    @asynccontextmanager
    async def tenant_session(self, org_id):
        self.opens += 1
        async with super().tenant_session(org_id) as s:
            yield s


async def test_idle_worker_opens_no_db_sessions_and_wakes_on_new_work(client, make_env, worker, monkeypatch):
    env = await make_env("idle")
    await drain(worker)  # clear jobs left by other tests so the worker can go idle
    db = CountingDb(make_engine(get_settings().worker_database_url))
    w = Worker(db=db)
    monkeypatch.setattr(w.s, "worker_idle_sweep_seconds", 3600)
    task = asyncio.create_task(w.run_forever())
    await asyncio.sleep(2.0)  # initial cycle: drain + stats + next-due, then idle on Redis
    settled = db.opens
    await asyncio.sleep(4.0)
    assert db.opens == settled, f"idle worker opened {db.opens - settled} DB sessions"
    assert (await metrics.queue_snapshot(w.redis))["worker_stale"] is False  # heartbeat keeps flowing without the DB

    t0 = time.monotonic()
    r = await client.post(f"{API}/documents", headers=env.h("manager"), files={"file": ("w.txt", b"wake probe note", "text/plain")})
    doc_id = r.json()["id"]
    while time.monotonic() - t0 < 15:
        d = (await client.get(f"{API}/documents/{doc_id}", headers=env.h("viewer"))).json()
        if d["status"] not in ("queued", "processing"):
            break
        await asyncio.sleep(0.25)
    assert d["status"] in ("completed", "requires_review"), d["status"]
    assert time.monotonic() - t0 < 15  # woken by the Redis signal, not by the 1 h sweep
    w._stop.set()
    await asyncio.wait_for(task, 10)


async def test_next_due_reflects_scheduled_retries(make_env, worker, worker_sql):
    env = await make_env("due")
    await drain(worker)
    worker_sql.execute(text("INSERT INTO jobs (id, org_id, kind, payload, status, run_at) VALUES (:i, :o, 'analyze', '{}', 'retry_scheduled', now() + interval '7 seconds')"),
                       {"i": str(uuid.uuid4()), "o": env.org_id})
    worker_sql.connection.commit()
    due = await worker.next_due_seconds()
    assert 3 <= due <= 8  # the worker sleeps until the retry is due, not for the whole idle sweep
