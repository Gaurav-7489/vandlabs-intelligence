import json
import time

from sqlalchemy import text

from app.core import metrics
from tests.conftest import drain, hdr, sample_csv, uniq

API = "/api/v1"


async def _platform_admin(owner_sql) -> str:
    email = f"{uniq('ops')}@vand.example.com"
    owner_sql.execute(text("INSERT INTO users (email, is_platform_admin) VALUES (:e, true)"), {"e": email})
    owner_sql.connection.commit()
    return email


async def test_metrics_endpoint_is_platform_admin_and_mfa_only(client, make_env, owner_sql):
    env = await make_env("opsacl")
    assert (await client.get(f"{API}/ops/metrics", headers=env.h("owner"))).status_code == 403  # tenant owner is not a platform admin
    admin = await _platform_admin(owner_sql)
    assert (await client.get(f"{API}/ops/metrics", headers=hdr(admin, mfa=False))).status_code == 403
    r = await client.get(f"{API}/ops/metrics", headers=hdr(admin))
    assert r.status_code == 200 and "counters" in r.json() and "queue" in r.json()


async def test_counters_track_requests_auth_failures_and_rate_limits(client, make_env, owner_sql, app_ctx):
    _, app, _ = app_ctx
    env = await make_env("opsc")
    admin = await _platform_admin(owner_sql)
    before = (await client.get(f"{API}/ops/metrics", headers=hdr(admin))).json()["counters"]
    await client.get(f"{API}/me", headers={"Authorization": "Bearer junk"})  # auth failure
    for _ in range(11):  # 11th exceeds the ai policy (10/min)
        await client.post(f"{API}/intelligence/ask", headers=env.h("staff"), json={"question": "anything at all"})
    after = (await client.get(f"{API}/ops/metrics", headers=hdr(admin))).json()
    c = after["counters"]
    assert c.get("auth.failure", 0) > before.get("auth.failure", 0)
    assert c.get("ratelimit.violation.ai", 0) > before.get("ratelimit.violation.ai", 0)
    assert c.get("http.2xx", 0) > before.get("http.2xx", 0) and c.get("http.4xx", 0) > before.get("http.4xx", 0)
    assert sum(after["latency_histogram_ms"].values()) > 0
    body = json.dumps(after)
    assert env.org_id not in body and "@" not in body  # aggregates only: no tenant ids or emails


async def test_worker_publishes_queue_snapshot_and_job_counters(client, make_env, worker, owner_sql, app_ctx):
    _, app, _ = app_ctx
    env = await make_env("opsq")
    admin = await _platform_admin(owner_sql)
    await client.post(f"{API}/documents", headers=env.h("manager"), files={"file": ("a.csv", sample_csv(), "text/csv")})
    await worker.publish_stats()
    q = (await client.get(f"{API}/ops/metrics", headers=hdr(admin))).json()["queue"]
    assert q["available"] and not q["worker_stale"] and q["by_status"].get("queued", 0) >= 1
    await drain(worker)
    c = (await client.get(f"{API}/ops/metrics", headers=hdr(admin))).json()["counters"]
    assert c.get("jobs.completed", 0) >= 2  # ingest + analyze


async def test_stale_worker_snapshot_is_flagged(app_ctx):
    _, app, _ = app_ctx
    r = app.state.vand.redis
    await r.set("ops:queue", json.dumps({"by_status": {}, "at": time.time() - 600}), ex=300)
    snap = await metrics.queue_snapshot(r)
    assert snap["worker_stale"] is True
    await r.delete("ops:queue")
    assert (await metrics.queue_snapshot(r))["worker_stale"] is True  # no snapshot at all => also stale
