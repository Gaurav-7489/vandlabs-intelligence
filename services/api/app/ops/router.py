"""Operations endpoints for VandLabs platform administrators. Aggregates only; no tenant content or identifiers."""
from typing import Annotated, Any

from fastapi import APIRouter, Depends

from app.core import metrics
from app.core.state import AppState, get_state
from app.identity.deps import Identity, get_platform_admin

router = APIRouter(prefix="/ops", tags=["ops"])

# Suggested alert thresholds (configure in your alerting tool; see docs/operations/observability.md)
THRESHOLDS = {"http.5xx_per_hour": 20, "auth.failure_per_hour": 100, "ratelimit_violations_per_hour": 500, "dead_letter": 1, "queued_oldest_age_seconds": 300}


@router.get("/metrics")
async def get_metrics(_: Annotated[Identity, Depends(get_platform_admin)], state: Annotated[AppState, Depends(get_state)], hours: int = 24) -> dict[str, Any]:
    hours = max(1, min(hours, 72))
    counters = await metrics.summary(state.redis, hours)
    lat = {k.removeprefix("http.latency."): v for k, v in counters.items() if k.startswith("http.latency.")}
    return {"window_hours": hours, "counters": counters, "latency_histogram_ms": lat, "queue": await metrics.queue_snapshot(state.redis), "thresholds": THRESHOLDS}
