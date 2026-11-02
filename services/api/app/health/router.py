from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.core.state import AppState, get_state

router = APIRouter(tags=["health"])


@router.get("/healthz")
async def liveness():
    return {"status": "ok"}  # process is up; says nothing about dependencies


@router.get("/readyz")
async def readiness(state: Annotated[AppState, Depends(get_state)]):
    checks: dict[str, str] = {}
    try:
        async with state.db.bare_session() as s:
            await s.execute(text("SELECT 1"))
        checks["database"] = "ok"
    except Exception:  # noqa: BLE001
        checks["database"] = "unavailable"
    checks["redis"] = "ok" if await state.limiter.ping() else "unavailable"
    checks["ai_provider"] = "configured" if state.ai.configured else "not_configured"
    ok = checks["database"] == "ok" and checks["redis"] == "ok"
    return JSONResponse({"status": "ready" if ok else "degraded", "checks": checks}, status_code=200 if ok else 503)
