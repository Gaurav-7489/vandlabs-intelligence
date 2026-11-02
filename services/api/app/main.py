import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware

from app.ai.gateway import AIGateway
from app.audit.router import router as audit_router
from app.core.config import Settings, get_settings
from app.core.db import Database, make_engine
from app.core.errors import install_error_handlers
from app.core.logging import configure_logging, get_logger, request_id_var
from app.core.ratelimit import RateLimiter
from app.core.state import AppState
from app.core.storage import make_storage
from app.decisions.router import router as decisions_router
from app.documents.router import router as documents_router
from app.health.router import router as health_router
from app.identity.router import router as identity_router
from app.identity.tokens import TokenVerifier
from app.intelligence.router import router as intelligence_router
from app.search.router import router as search_router
from app.tasks.router import router as tasks_router

log = get_logger("http")

SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff", "X-Frame-Options": "DENY", "Referrer-Policy": "no-referrer",
    "Strict-Transport-Security": "max-age=63072000; includeSubDomains",
    "Content-Security-Policy": "default-src 'none'; frame-ancestors 'none'",  # API serves JSON only
    "Cache-Control": "no-store",  # tenant data must never sit in shared caches
    "Permissions-Policy": "geolocation=(), microphone=(), camera=()",
}


def create_app(settings: Settings | None = None, ai: AIGateway | None = None) -> FastAPI:
    s = settings or get_settings()
    configure_logging()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        db = Database(make_engine(s.database_url, s))
        app.state.vand = AppState(settings=s, db=db, limiter=RateLimiter(s.redis_url), verifier=TokenVerifier(s),
                                  storage=make_storage(s), ai=ai or AIGateway(s))
        yield
        await app.state.vand.limiter.close()
        await db.dispose()

    app = FastAPI(title="VandLabs Intelligence API", version="0.1.0", lifespan=lifespan,
                  docs_url=None if s.env == "production" else "/docs", redoc_url=None,
                  openapi_url=None if s.env == "production" else "/openapi.json")
    install_error_handlers(app)
    app.add_middleware(CORSMiddleware, allow_origins=s.cors_origin_list, allow_methods=["GET", "POST", "PATCH", "DELETE"],
                       allow_headers=["authorization", "content-type", "x-org-id", "idempotency-key"], allow_credentials=False,
                       expose_headers=["x-request-id", "retry-after"])

    @app.middleware("http")
    async def request_context(request: Request, call_next):  # type: ignore[no-untyped-def]
        rid = request.headers.get("x-request-id", "")[:64] or uuid.uuid4().hex
        request.state.request_id = rid
        token = request_id_var.set(rid)
        try:
            # Reject oversized bodies up front when the client declares a length.
            declared = request.headers.get("content-length")
            if declared and declared.isdigit() and int(declared) > s.max_upload_bytes + 1024 * 1024:
                resp: Response = Response(status_code=413, content='{"error":{"code":"payload_too_large","message":"Request too large"}}',
                                          media_type="application/json")
            else:
                resp = await call_next(request)
            for k, v in SECURITY_HEADERS.items():
                resp.headers.setdefault(k, v)
            resp.headers["X-Request-ID"] = rid
            log.info("request", extra={"method": request.method, "path": request.url.path, "status": resp.status_code})
            return resp
        finally:
            request_id_var.reset(token)

    app.include_router(health_router)
    api = "/api/v1"
    for r in (identity_router, documents_router, search_router, intelligence_router, decisions_router, tasks_router, audit_router):
        app.include_router(r, prefix=api)
    return app
