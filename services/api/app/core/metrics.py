"""Minimal operational metrics: hourly counters in Redis (HINCRBY) + a worker-published queue snapshot.
Aggregates only - never tenant content or identifiers. Failures to record a metric never affect the request."""
import json
import time
from typing import Any

import redis.asyncio as aioredis

RETENTION_HOURS = 72
LAT_BUCKETS_MS = (50, 100, 250, 500, 1000, 5000)
HEARTBEAT_KEY = "ops:worker:heartbeat"


def _hour(ts: float | None = None) -> str:
    return time.strftime("%Y%m%d%H", time.gmtime(ts or time.time()))


async def incr(r: aioredis.Redis, field: str, by: int = 1) -> None:
    try:
        key = f"m:{_hour()}"
        pipe = r.pipeline()
        pipe.hincrby(key, field, by)
        pipe.expire(key, RETENTION_HOURS * 3600)
        await pipe.execute()
    except Exception:  # noqa: BLE001 - metrics are best-effort
        return


async def observe_request(r: aioredis.Redis, status: int, ms: float) -> None:
    await incr(r, f"http.{status // 100}xx")
    bucket = next((f"le_{b}" for b in LAT_BUCKETS_MS if ms <= b), "gt_5000")
    await incr(r, f"http.latency.{bucket}")


async def summary(r: aioredis.Redis, hours: int = 24) -> dict[str, int]:
    now = time.time()
    total: dict[str, int] = {}
    for h in range(hours):
        for k, v in (await r.hgetall(f"m:{_hour(now - h * 3600)}")).items():
            k = k if isinstance(k, str) else k.decode()
            total[k] = total.get(k, 0) + int(v)
    return dict(sorted(total.items()))


async def publish_queue_snapshot(r: aioredis.Redis, snap: dict[str, Any]) -> None:
    await r.set("ops:queue", json.dumps({**snap, "at": time.time()}), ex=7200)


async def queue_snapshot(r: aioredis.Redis) -> dict[str, Any]:
    hb = await r.get(HEARTBEAT_KEY)
    hb_age = round(time.time() - float(hb), 1) if hb else None
    raw = await r.get("ops:queue")
    snap: dict[str, Any] = json.loads(raw) if raw else {}
    snap["available"] = bool(raw)
    snap["age_seconds"] = round(time.time() - snap["at"], 1) if raw else None  # queue counts are refreshed after each work cycle
    snap["heartbeat_age_seconds"] = hb_age
    snap["worker_stale"] = hb_age is None or hb_age > 90  # liveness comes from the Redis heartbeat (every 30 s)
    return snap
