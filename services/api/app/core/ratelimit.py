"""Distributed token-bucket limiter (Redis + Lua, atomic). Counters are shared across API replicas.

Failure policy when Redis is unavailable: policies marked `fail_closed` (auth, uploads, AI, search) reject with 503;
cheap read policies fail open and the event is logged.
"""
import time
from dataclasses import dataclass

import redis.asyncio as aioredis

from app.core import metrics
from app.core.errors import RateLimited, Unavailable
from app.core.logging import get_logger

log = get_logger("ratelimit")

_LUA = """
local key = KEYS[1]
local capacity = tonumber(ARGV[1]); local refill = tonumber(ARGV[2]); local now = tonumber(ARGV[3])
local data = redis.call('HMGET', key, 'tokens', 'ts')
local tokens = tonumber(data[1]); local ts = tonumber(data[2])
if tokens == nil then tokens = capacity; ts = now end
tokens = math.min(capacity, tokens + (now - ts) * refill)
local allowed = 0; local retry = 0
if tokens >= 1 then tokens = tokens - 1; allowed = 1 else retry = math.ceil((1 - tokens) / refill) end
redis.call('HSET', key, 'tokens', tokens, 'ts', now)
redis.call('EXPIRE', key, math.ceil(capacity / refill) + 60)
return {allowed, retry}
"""


@dataclass(frozen=True)
class Policy:
    name: str
    limit: int  # requests per window
    window_seconds: int
    fail_closed: bool = False

    @property
    def refill_per_second(self) -> float:
        return self.limit / self.window_seconds


# Starting policies (configurable per deployment after load testing).
POLICIES: dict[str, Policy] = {p.name: p for p in [
    Policy("read", 120, 60),
    Policy("write", 30, 60),
    Policy("search", 20, 60, fail_closed=True),
    Policy("ai", 10, 60, fail_closed=True),
    Policy("upload", 10, 3600, fail_closed=True),
    Policy("auth_failure", 5, 900, fail_closed=True),
    Policy("auth_flow", 30, 60, fail_closed=True),
    Policy("org_read", 3000, 60),
]}


class RateLimiter:
    def __init__(self, url: str):
        self._redis = aioredis.from_url(url, decode_responses=True, socket_timeout=0.5, socket_connect_timeout=0.5)
        self._script = self._redis.register_script(_LUA)

    async def hit(self, policy_name: str, subject: str) -> None:
        policy = POLICIES[policy_name]
        try:
            allowed, retry = await self._script(
                keys=[f"rl:{policy.name}:{subject}"], args=[policy.limit, policy.refill_per_second, time.time()])
        except Exception as exc:  # noqa: BLE001 - any Redis failure is handled by policy
            log.error("ratelimiter_unavailable", extra={"policy": policy.name, "err": type(exc).__name__})
            if policy.fail_closed:
                raise Unavailable("Service temporarily unavailable", headers={"Retry-After": "5"}) from None
            return
        if not allowed:
            await metrics.incr(self._redis, f"ratelimit.violation.{policy.name}")
            raise RateLimited("Rate limit exceeded", headers={"Retry-After": str(max(1, int(retry)))})

    async def acquire_slot(self, name: str, subject: str, max_concurrent: int, ttl: int = 120) -> str:
        """Concurrency cap (e.g. simultaneous AI generations). Slots expire on their own so a crashed request cannot leak capacity."""
        key = f"conc:{name}:{subject}"
        token = f"{time.time()}"
        try:
            pipe = self._redis.pipeline()
            pipe.zremrangebyscore(key, 0, time.time() - ttl)
            pipe.zadd(key, {token: time.time()})
            pipe.zcard(key)
            pipe.expire(key, ttl)
            n = (await pipe.execute())[2]
        except Exception:  # noqa: BLE001
            raise Unavailable("Service temporarily unavailable", headers={"Retry-After": "5"}) from None
        if n > max_concurrent:
            await self._redis.zrem(key, token)
            raise RateLimited("Too many concurrent requests", headers={"Retry-After": "3"})
        return token

    async def release_slot(self, name: str, subject: str, token: str) -> None:
        try:
            await self._redis.zrem(f"conc:{name}:{subject}", token)
        except Exception as exc:  # noqa: BLE001 - slot also expires by TTL
            log.warning("slot_release_failed", extra={"err": type(exc).__name__})

    async def ping(self) -> bool:
        try:
            return bool(await self._redis.ping())
        except Exception:  # noqa: BLE001
            return False

    async def close(self) -> None:
        await self._redis.aclose()
