import asyncio
import uuid

from sqlalchemy import text

from app.core.config import get_settings
from app.core.db import Database, make_engine
from app.core.errors import RateLimited
from app.core.ratelimit import POLICIES, RateLimiter
from app.jobs import queue
from app.worker import Worker
from tests.conftest import drain, hdr, uniq

API = "/api/v1"


async def test_limiter_is_atomic_across_replicas_under_concurrency():
    """Many concurrent hits through several independent limiter instances (= API replicas) must admit exactly `limit`."""
    replicas = [RateLimiter(get_settings().redis_url) for _ in range(4)]
    subject = uniq("user")
    limit = POLICIES["ai"].limit

    async def one(i: int) -> bool:
        try:
            await replicas[i % 4].hit("ai", subject)
            return True
        except RateLimited:
            return False
    results = await asyncio.gather(*(one(i) for i in range(120)))
    for r in replicas:
        await r.close()
    assert sum(results) == limit


async def test_limits_are_independent_per_tenant_and_user():
    r = RateLimiter(get_settings().redis_url)
    a, b = uniq("a"), uniq("b")
    for _ in range(POLICIES["ai"].limit):
        await r.hit("ai", a)
    try:
        await r.hit("ai", a)
        raise AssertionError("expected limit")
    except RateLimited:
        pass
    await r.hit("ai", b)  # another user unaffected
    await r.close()


async def test_legitimate_dashboard_usage_is_not_throttled(client, make_env):
    env = await make_env("dash")
    for _ in range(15):  # a dashboard load + navigation burst: kpis, deadlines, pending decisions, insights, tasks...
        for path in ("/overview/kpis", "/overview/deadlines", "/decisions", "/insights", "/tasks"):
            assert (await client.get(f"{API}{path}", headers=env.h("manager"))).status_code == 200


async def test_concurrent_ai_generation_cap(client, make_env, gateway, fake, app_ctx):
    env = await make_env("conc")
    gate = asyncio.Event()
    started = 0

    class Slow:
        name, model = "slow", "slow-1"

        async def complete(self, system, user, max_tokens, timeout):
            nonlocal started
            started += 1
            await gate.wait()
            from app.ai.gateway import Completion
            return Completion('{"answer":"x","citations":["C1"],"insufficient_evidence":false}', "slow", "slow-1", 1, 1)
    gateway.providers = [Slow()]
    await client.post(f"{API}/documents", headers=env.h("manager"), files={"file": ("n.txt", b"zephyr delivery note", "text/plain")})
    w = Worker(db=Database(make_engine(get_settings().worker_database_url)))
    await drain(w)
    await w.db.dispose()
    ask = lambda: client.post(f"{API}/intelligence/ask", headers=env.h("staff"), json={"question": "zephyr delivery"})  # noqa: E731
    t1, t2 = asyncio.create_task(ask()), asyncio.create_task(ask())
    for _ in range(50):
        if started == 2:
            break
        await asyncio.sleep(0.05)
    third = await ask()
    assert third.status_code == 429 and third.headers["retry-after"]
    gate.set()
    assert [(await t).status_code for t in (t1, t2)] == [200, 200]
    assert (await ask()).status_code == 200  # slots released


async def test_org_wide_quota_applies_across_users(app_ctx, make_env):
    from app.core.ratelimit import Policy
    client, app, _ = app_ctx
    env, other = await make_env("orgq"), await make_env("orgq2")
    POLICIES["org_read"] = Policy("org_read", 5, 60)
    try:
        codes = []
        for role in ("viewer", "manager", "staff", "auditor", "manager2", "viewer"):
            codes.append((await client.get(f"{API}/documents", headers=env.h(role))).status_code)
        assert codes[:5] == [200] * 5 and codes[5] == 429
        assert (await client.get(f"{API}/documents", headers=other.h("viewer"))).status_code == 200  # other tenant unaffected
    finally:
        POLICIES["org_read"] = Policy("org_read", 3000, 60)


async def test_job_queue_is_bounded_per_org(client, make_env, monkeypatch):
    env = await make_env("qb")
    monkeypatch.setattr(get_settings(), "max_queued_jobs_per_org", 2)
    codes = [(await client.post(f"{API}/intelligence/analyze", headers=env.h("manager"))).status_code for _ in range(4)]
    assert codes == [202, 202, 429, 429]


async def test_two_workers_never_run_the_same_job_twice(client, make_env, worker_sql):
    env = await make_env("mw")
    for i in range(12):  # spread across users: the per-user upload limit (10/h) is itself enforced
        r = await client.post(f"{API}/documents", headers=env.h(("manager", "manager2", "staff")[i % 3]), files={"file": (f"n{i}.txt", f"note {i} {uniq('x')}".encode(), "text/plain")})
        assert r.status_code == 202
    w1, w2 = (Worker(db=Database(make_engine(get_settings().worker_database_url))) for _ in range(2))
    done = await asyncio.gather(drain(w1), drain(w2))
    await w1.db.dispose()
    await w2.db.dispose()
    assert sum(done) >= 12
    rows = worker_sql.execute(text("SELECT attempts, status FROM jobs WHERE org_id = :o AND kind = 'ingest_document'"), {"o": env.org_id}).all()
    assert len(rows) == 12 and all(a == 1 and s == "completed" for a, s in rows)  # each claimed exactly once


async def test_enqueue_dedup_survives_concurrent_callers(make_env, client):
    env = await make_env("dd")
    db = Database(make_engine(get_settings().database_url))
    org = uuid.UUID(env.org_id)

    async def go():
        async with db.tenant_session(org) as s:
            return (await queue.enqueue(s, org_id=org, kind="analyze", payload={}, idempotency_key="same-key")).id
    ids = await asyncio.gather(*(go() for _ in range(5)), return_exceptions=True)
    await db.dispose()
    ok = {i for i in ids if isinstance(i, uuid.UUID)}
    assert len(ok) == 1  # losers either returned the existing job or hit the unique index; never two jobs
    _ = hdr
