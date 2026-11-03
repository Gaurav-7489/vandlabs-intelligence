"""Analysis orchestration: run deterministic rules, upsert insights (idempotent), auto-resolve cleared conditions."""
from datetime import date
from typing import Any
from uuid import UUID

from sqlalchemy import case, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.intelligence.rules import evaluate
from app.models import Commitment, Insight, Task


async def run_analysis(session: AsyncSession, s: Settings, org_id: UUID, today: date | None = None) -> dict[str, Any]:
    today = today or date.today()
    commitments = list((await session.execute(select(Commitment))).scalars())
    tasks = list((await session.execute(select(Task))).scalars())
    by_key = {c.external_key: c for c in commitments}
    findings = evaluate(commitments, tasks, today, s.risk_due_soon_days)
    seen: set[str] = set()
    for f in findings:
        seen.add(f.fingerprint)
        c = by_key[f.commitment_key]
        stmt = insert(Insight).values(
            org_id=org_id, fingerprint=f.fingerprint, rule=f.rule, severity=f.severity, title=f.title, summary=f.summary,
            commitment_id=c.id, evidence=f.evidence, uncertainty=f.uncertainty, recommended_step=f.recommended_step)
        await session.execute(stmt.on_conflict_do_update(
            index_elements=["org_id", "fingerprint"],
            set_={"severity": stmt.excluded.severity, "title": stmt.excluded.title, "summary": stmt.excluded.summary,
                  "evidence": stmt.excluded.evidence, "uncertainty": stmt.excluded.uncertainty,
                  "recommended_step": stmt.excluded.recommended_step, "commitment_id": stmt.excluded.commitment_id,
                  # a previously resolved condition that recurs re-opens; dismissed/acknowledged stay as set by a human
                  "status": case((Insight.status == "resolved", "open"), else_=Insight.status),
                  "updated_at": func.now()}))
    resolved = 0
    for ins in (await session.execute(select(Insight).where(Insight.status.in_(["open", "acknowledged"])))).scalars():
        if ins.fingerprint not in seen:
            ins.status = "resolved"
            resolved += 1
    return {"findings": len(findings), "auto_resolved": resolved, "as_of": today.isoformat()}
