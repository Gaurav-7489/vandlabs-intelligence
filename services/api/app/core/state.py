from dataclasses import dataclass

import redis.asyncio as aioredis
from fastapi import Request

from app.ai.gateway import AIGateway
from app.core.config import Settings
from app.core.db import Database
from app.core.ratelimit import RateLimiter
from app.core.storage import Storage
from app.identity.oidc import OidcClient
from app.identity.sessions import SessionStore
from app.identity.tokens import TokenVerifier


@dataclass
class AppState:
    settings: Settings
    db: Database
    limiter: RateLimiter
    verifier: TokenVerifier
    storage: Storage
    ai: AIGateway
    redis: aioredis.Redis
    oidc: OidcClient | None
    sessions: SessionStore


def get_state(request: Request) -> AppState:
    return request.app.state.vand
