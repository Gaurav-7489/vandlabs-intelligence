"""Document ingestion pipeline (runs in the worker, tenant-scoped, idempotent per document version)."""
import asyncio
from typing import Any
from uuid import UUID

from sqlalchemy import delete, select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit import service as audit
from app.core.config import Settings
from app.core.logging import get_logger
from app.core.storage import Storage, TenantStorage
from app.ingestion.extract import extract
from app.ingestion.parsers import ParseLimitExceeded
from app.ingestion.sandbox import run_sandboxed
from app.ingestion.scan import Scanner
from app.jobs import queue
from app.models import Commitment, Document, DocumentChunk, Task

log = get_logger("ingestion")


class HoldForRetry(Exception):
    """Raise to roll back and retry the job while persisting a visible hold state on the document afterwards."""

    def __init__(self, document_id: UUID, **fields: str):
        super().__init__("held for retry")
        self.document_id, self.fields = document_id, fields


async def ingest_document(session: AsyncSession, storage: Storage, scanner: Scanner, s: Settings, org_id: UUID, document_id: UUID) -> dict[str, Any]:
    doc = (await session.execute(select(Document).where(Document.id == document_id, Document.deleted_at.is_(None)))).scalar_one_or_none()
    if doc is None:
        return {"skipped": "document missing or deleted"}
    doc.status = "processing"
    await session.flush()
    try:
        data = await TenantStorage(storage, org_id).get(doc.storage_key)
    except Exception as e:  # noqa: BLE001 - storage hiccup: let the job retry (raise) rather than mark the file failed
        raise RuntimeError(f"storage read failed: {type(e).__name__}") from None
    # ---- Security gate: nothing is parsed, indexed or searchable until the scan outcome is known and acceptable. ----
    res = await scanner.scan(data)
    doc.scan_detail = res.detail or None
    if res.status == "infected":
        doc.scan_status, doc.status, doc.error = "infected", "quarantined", "File rejected by malware scan"
        await session.execute(delete(DocumentChunk).where(DocumentChunk.document_id == doc.id))
        await audit.record(session, action="document.quarantined", org_id=org_id, actor=doc.uploaded_by, resource_type="document",
                           resource_id=doc.id, outcome="denied", signature=res.detail)
        return {"status": "quarantined"}
    if res.status == "unavailable":
        if s.scan_required:
            raise HoldForRetry(doc.id, scan_status="unavailable", status="scan_pending",
                               error="Security scan unavailable; processing is held and will be retried")  # file stays unindexed
        doc.scan_status = "not_performed"  # development only: explicitly NOT claimed as scanned
    else:
        doc.scan_status = "clean"
    try:
        parsed = await asyncio.to_thread(run_sandboxed, doc.detected_type, data, s)
    except ParseLimitExceeded as e:
        doc.status, doc.error = "failed", f"Parsing limit exceeded: {e}"
        return {"status": "failed"}
    except Exception as e:  # noqa: BLE001 - corrupt/hostile file: fail the document, not the worker
        log.warning("parse_failed", extra={"document_id": str(doc.id), "err": type(e).__name__})
        doc.status, doc.error = "failed", "The file could not be parsed"
        return {"status": "failed"}

    ex = extract(parsed.tables)
    # Replace derived data for this document (idempotent reprocessing).
    await session.execute(delete(DocumentChunk).where(DocumentChunk.document_id == doc.id))
    chunks = list(parsed.chunks)
    for rec in [*ex.commitments, *ex.tasks]:
        chunks.append((f"{rec['title']} | owner: {rec.get('owner_name') or 'unassigned'} | due: {rec['due_date'] or 'none'} | status: {rec['status']}"
                       + (f" | customer: {rec['customer']}" if rec.get("customer") else ""), rec["source_locator"]))
    for i, (txt, loc) in enumerate(chunks):
        session.add(DocumentChunk(org_id=org_id, document_id=doc.id, ordinal=i, text=txt, locator=loc))

    for rec in ex.commitments:
        stmt = insert(Commitment).values(org_id=org_id, source_document_id=doc.id, **rec)
        await session.execute(stmt.on_conflict_do_update(
            index_elements=["org_id", "external_key"],
            set_={k: stmt.excluded[k] for k in (*rec.keys(), "source_document_id")} | {"updated_at": text("now()")}))
    for rec in ex.tasks:
        stmt = insert(Task).values(org_id=org_id, source_document_id=doc.id, origin="imported", **rec)
        await session.execute(stmt.on_conflict_do_update(
            index_elements=["org_id", "external_key"], index_where=text("external_key IS NOT NULL"),
            set_={k: stmt.excluded[k] for k in (*rec.keys(), "source_document_id")} | {"updated_at": text("now()")}))

    stats = {"chunks": len(chunks), "commitments": len(ex.commitments), "tasks": len(ex.tasks), "rejected_rows": ex.rejected[:50],
             "rejected_count": len(ex.rejected), "unmapped_tables": ex.unmapped_tables, "notes": parsed.notes}
    doc.stats = stats
    needs_review = bool(ex.rejected or parsed.notes) or (not chunks)
    doc.status = "requires_review" if needs_review else "completed"
    doc.error = "; ".join(parsed.notes) or (f"{len(ex.rejected)} rows could not be mapped" if ex.rejected else None)
    if ex.commitments or ex.tasks:
        await queue.enqueue(session, org_id=org_id, kind="analyze", payload={}, idempotency_key=f"analyze:{doc.id}:{doc.version}:{doc.sha256[:12]}")
    return {"status": doc.status, **{k: v for k, v in stats.items() if isinstance(v, int)}}
