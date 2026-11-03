from typing import Annotated

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.core.dbsafety import check_role_safety
from app.core.state import AppState, get_state

router = APIRouter(tags=["health"])


@router.get("/healthz")
async def liveness():
    return {"status": "ok"}  # process is up; says nothing about dependencies


@router.get("/readyz")
async def readiness(request: Request, state: Annotated[AppState, Depends(get_state)]):
    checks: dict[str, str] = {}
    try:
        async with state.db.bare_session() as s:
            await s.execute(text("SELECT 1"))
        checks["database"] = "ok"
    except Exception:  # noqa: BLE001
        checks["database"] = "unavailable"
    try:
        async with state.db.bare_session() as s:
            safety = await check_role_safety(s)
        checks["db_role"] = "ok" if safety.ok else "unsafe"
    except Exception:  # noqa: BLE001
        checks["db_role"] = "unknown"
    checks["redis"] = "ok" if await state.limiter.ping() else "unavailable"
    checks["ai_provider"] = "configured" if state.ai.configured else "not_configured"
    ok = checks["database"] == "ok" and checks["redis"] == "ok" and checks["db_role"] != "unsafe"
    body: dict[str, object] = {"status": "ready" if ok else "degraded"}
    if getattr(request.state, "edge_trusted", False):  # dependency detail only for callers that proved they are the edge / local
        body["checks"] = checks
    return JSONResponse(body, status_code=200 if ok else 503)
