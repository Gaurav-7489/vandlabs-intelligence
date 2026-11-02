from dataclasses import dataclass

from fastapi import Request

from app.ai.gateway import AIGateway
from app.core.config import Settings
from app.core.db import Database
from app.core.ratelimit import RateLimiter
from app.core.storage import Storage
from app.identity.tokens import TokenVerifier


@dataclass
class AppState:
    settings: Settings
    db: Database
    limiter: RateLimiter
    verifier: TokenVerifier
    storage: Storage
    ai: AIGateway


def get_state(request: Request) -> AppState:
    return request.app.state.vand
