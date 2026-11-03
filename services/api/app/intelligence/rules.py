"""Deterministic commitment-risk rules. Pure functions over records: no I/O, no LLM. Every finding carries the
exact records and values that triggered it so a human can verify it."""
import hashlib
from dataclasses import dataclass
from datetime import date
from typing import Any

CLOSED = {"done", "cancelled"}


@dataclass
class Finding:
    fingerprint: str
    rule: str
    severity: str
    title: str
    summary: str
    commitment_key: str
    evidence: list[dict[str, Any]]
    uncertainty: str
    recommended_step: str


def _fp(*parts: str) -> str:
    return hashlib.sha256("|".join(parts).encode()).hexdigest()


def _ev(kind: str, rec: Any, **facts: Any) -> dict[str, Any]:
    return {"type": kind, "id": str(rec.id), "key": rec.external_key, "document_id": str(rec.source_document_id) if rec.source_document_id else None,
            "locator": rec.source_locator, "facts": {"title": rec.title, "due_date": rec.due_date.isoformat() if rec.due_date else None,
                                                     "status": rec.status, "owner": rec.owner_name, **facts}}


def evaluate(commitments: list[Any], tasks: list[Any], today: date, due_soon_days: int = 14) -> list[Finding]:
    tasks_by_key = {t.external_key: t for t in tasks if t.external_key}
    findings: list[Finding] = []
    for c in commitments:
        if c.status in CLOSED or c.due_date is None:
            continue
        days_left = (c.due_date - today).days
        near = days_left <= due_soon_days
        staleness = "Based on the uploaded data only; the source file may be out of date relative to current work."

        if days_left < 0:
            findings.append(Finding(
                _fp("commitment_overdue", c.org_id.hex, c.external_key), "commitment_overdue", "high",
                f"Overdue commitment: {c.title}",
                f"Commitment '{c.title}' was due {c.due_date.isoformat()} ({-days_left} day(s) ago) and is still '{c.status}'.",
                c.external_key, [_ev("commitment", c, days_overdue=-days_left)], staleness,
                f"Confirm status with {c.owner_name or 'the responsible owner'} and agree a revised delivery date with {c.customer or 'the customer'}."))

        blockers = []
        for dep in c.depends_on or []:
            t = tasks_by_key.get(dep)
            if t is None or t.status in CLOSED:
                continue
            reasons = []
            if t.due_date and t.due_date < today:
                reasons.append(f"overdue since {t.due_date.isoformat()}")
            if t.status == "blocked":
                reasons.append("marked blocked")
            if t.due_date and t.due_date > c.due_date:
                reasons.append(f"due {t.due_date.isoformat()}, after the commitment deadline")
            if reasons:
                blockers.append((t, reasons))
        if blockers and near:
            sev = "high" if days_left <= 7 else "medium"
            names = "; ".join(f"'{t.title}' ({', '.join(r)})" for t, r in blockers)
            ev = [_ev("commitment", c, days_left=days_left)] + [_ev("task", t, problems=r) for t, r in blockers]
            t0 = blockers[0][0]
            findings.append(Finding(
                _fp("commitment_blocked", c.org_id.hex, c.external_key, *sorted(t.external_key or "" for t, _ in blockers)),
                "commitment_blocked_by_task", sev,
                f"At risk: {c.title}",
                f"Commitment '{c.title}' is due {c.due_date.isoformat()} ({days_left} day(s) from {today.isoformat()}) but depends on: {names}.",
                c.external_key, ev,
                staleness + " Dependency links come from the 'depends on' column of the source file; undeclared dependencies are not detected.",
                f"Escalate '{t0.title}' to {t0.owner_name or 'an owner'} and decide whether to re-plan or renegotiate the commitment."))

        if near and not c.owner_name and not c.owner_email:
            findings.append(Finding(
                _fp("commitment_unowned", c.org_id.hex, c.external_key), "commitment_unowned", "medium",
                f"No owner for: {c.title}", f"Commitment '{c.title}' is due {c.due_date.isoformat()} and has no responsible owner recorded.",
                c.external_key, [_ev("commitment", c, days_left=days_left)], staleness,
                "Assign an accountable owner."))
    return findings
