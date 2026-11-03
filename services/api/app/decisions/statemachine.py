"""Decision lifecycle with validated transitions. The frontend can never set `state` directly."""
from app.core.errors import Conflict

TRANSITIONS: dict[str, frozenset[str]] = {
    "detected": frozenset({"under_analysis", "recommendation_ready"}),
    "under_analysis": frozenset({"recommendation_ready"}),
    "recommendation_ready": frozenset({"awaiting_approval"}),
    "awaiting_approval": frozenset({"approved", "rejected", "deferred"}),
    "approved": frozenset({"in_execution"}),
    "in_execution": frozenset({"completed", "approved"}),  # failed execution returns to approved for retry
    "completed": frozenset({"outcome_measured"}),
    "outcome_measured": frozenset({"closed"}),
    "rejected": frozenset({"reopened"}),
    "deferred": frozenset({"reopened"}),
    "closed": frozenset({"reopened"}),
    "reopened": frozenset({"recommendation_ready"}),
}


def check(current: str, target: str) -> None:
    if target not in TRANSITIONS.get(current, frozenset()):
        raise Conflict(f"Invalid transition: {current} -> {target}", current=current, target=target)
