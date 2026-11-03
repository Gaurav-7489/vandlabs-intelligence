"""Server-side sessions in Redis. The browser holds only an opaque random id in an HttpOnly cookie.

Records (incl. the IdP refresh token) are Fernet-encrypted when `session_encryption_key` is set (required in staging/production).
Limits: sliding idle timeout, absolute lifetime, periodic IdP revalidation (bounds how long a revoked/disabled user keeps access)."""
import json
import secrets
import time
from typing import Any

import redis.asyncio as aioredis
from cryptography.fernet import Fernet, InvalidToken

from app.core.config import Settings
from app.core.logging import get_logger
from app.identity.oidc import OidcClient, OidcError

log = get_logger("sessions")


class SessionStore:
    def __init__(self, r: aioredis.Redis, s: Settings, oidc: OidcClient | None):
        self.r, self.s, self.oidc = r, s, oidc
        self.fernet = Fernet(s.session_encryption_key.encode()) if s.session_encryption_key else None

    def _enc(self, rec: dict[str, Any]) -> str:
        raw = json.dumps(rec)
        return self.fernet.encrypt(raw.encode()).decode() if self.fernet else raw

    def _dec(self, blob: str) -> dict[str, Any] | None:
        try:
            raw = self.fernet.decrypt(blob.encode()).decode() if self.fernet else blob
            return json.loads(raw)  # type: ignore[no-any-return]
        except (InvalidToken, ValueError):
            return None

    async def create(self, *, subject: str, email: str | None, email_verified: bool, name: str | None, amr: list[str],
                     refresh_token: str | None, id_token: str) -> tuple[str, dict[str, Any]]:
        sid = secrets.token_urlsafe(32)
        now = time.time()
        rec = {"sub": subject, "email": email, "email_verified": email_verified, "name": name, "amr": amr, "refresh_token": refresh_token,
               "id_token": id_token, "csrf": secrets.token_urlsafe(32), "created": now, "revalidate_at": now + self.s.session_revalidate_seconds}
        pipe = self.r.pipeline()
        pipe.set(f"sess:{sid}", self._enc(rec), ex=self.s.session_idle_ttl_seconds)
        pipe.sadd(f"usess:{subject}", sid)
        pipe.expire(f"usess:{subject}", self.s.session_absolute_ttl_seconds)
        await pipe.execute()
        return sid, rec

    async def get(self, sid: str) -> dict[str, Any] | None:
        blob = await self.r.get(f"sess:{sid}")
        rec = self._dec(blob if isinstance(blob, str) else blob.decode()) if blob else None
        if rec is None:
            return None
        now = time.time()
        if now - rec["created"] > self.s.session_absolute_ttl_seconds:
            await self.delete(sid, rec["sub"])
            return None
        if now >= rec["revalidate_at"] and rec.get("refresh_token") and self.oidc:
            if not await self._revalidate(sid, rec):
                return None
        await self.r.expire(f"sess:{sid}", self.s.session_idle_ttl_seconds)  # sliding idle window
        return rec

    async def _revalidate(self, sid: str, rec: dict[str, Any]) -> bool:
        """Ask the IdP whether the grant is still valid (refresh-token rotation). Revoked/disabled => session ends."""
        assert self.oidc is not None
        if not await self.r.set(f"sesslock:{sid}", "1", nx=True, ex=10):  # single refresher per session (rotation-safe)
            return True
        try:
            ts = await self.oidc.refresh(rec["refresh_token"])
        except OidcError as e:
            if e.permanent:
                log.info("session_revoked_by_idp")
                await self.delete(sid, rec["sub"])
                return False
            return True  # IdP outage: keep the session until the next window rather than logging everyone out
        finally:
            await self.r.delete(f"sesslock:{sid}")
        rec["refresh_token"] = ts.refresh_token or rec["refresh_token"]
        rec["revalidate_at"] = time.time() + self.s.session_revalidate_seconds
        await self.r.set(f"sess:{sid}", self._enc(rec), ex=self.s.session_idle_ttl_seconds)
        return True

    async def delete(self, sid: str, subject: str | None = None) -> None:
        await self.r.delete(f"sess:{sid}")
        if subject:
            await self.r.srem(f"usess:{subject}", sid)

    async def delete_all(self, subject: str) -> int:
        sids = await self.r.smembers(f"usess:{subject}")
        if sids:
            await self.r.delete(*[f"sess:{x if isinstance(x, str) else x.decode()}" for x in sids])
        await self.r.delete(f"usess:{subject}")
        return len(sids)
