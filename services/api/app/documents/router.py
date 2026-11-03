import hashlib
import uuid
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, File, UploadFile
from sqlalchemy import delete, func, select

from app.audit import service as audit
from app.core import metrics
from app.core.errors import NotFound, PayloadTooLarge, Unavailable
from app.core.pagination import page
from app.core.state import AppState, get_state
from app.core.storage import StorageError, TenantStorage
from app.identity.deps import Principal, require
from app.identity.permissions import P
from app.ingestion.validate import detect_type, sanitize_filename
from app.jobs import queue
from app.models import Commitment, Document, DocumentChunk, Task

router = APIRouter(prefix="/documents", tags=["documents"])


def _view(d: Document) -> dict:
    return {"id": d.id, "filename": d.filename, "type": d.detected_type, "size_bytes": d.size_bytes, "status": d.status, "scan_status": d.scan_status,
            "error": d.error, "stats": d.stats, "version": d.version, "created_at": d.created_at, "updated_at": d.updated_at}


@router.post("", status_code=202)
async def upload(file: Annotated[UploadFile, File()], p: Annotated[Principal, Depends(require(P.DOCS_WRITE))],
                 state: Annotated[AppState, Depends(get_state)]):
    await state.limiter.hit("upload", f"user:{p.user.id}")
    s = state.settings
    buf = bytearray()
    while chunk := await file.read(1024 * 1024):  # bounded read: never buffer more than limit+1
        buf.extend(chunk)
        if len(buf) > s.max_upload_bytes:
            raise PayloadTooLarge("File exceeds the maximum upload size")
    data = bytes(buf)
    name = sanitize_filename(file.filename or "upload")
    kind = detect_type(name, data, s)
    sha = hashlib.sha256(data).hexdigest()
    dup = (await p.session.execute(select(Document).where(Document.sha256 == sha, Document.deleted_at.is_(None)))).scalar_one_or_none()
    if dup is not None:
        return {**_view(dup), "duplicate": True}
    doc_id = uuid.uuid4()
    key = f"{p.org_id}/{doc_id}"  # server-generated; user filename never touches storage paths
    try:
        await TenantStorage(state.storage, p.org_id).put(key, data)
    except StorageError:
        await metrics.incr(state.redis, "storage.error")
        raise Unavailable("File storage is temporarily unavailable", headers={"Retry-After": "10"}) from None
    doc = Document(id=doc_id, org_id=p.org_id, filename=name, detected_type=kind, size_bytes=len(data), sha256=sha,
                   storage_key=key, status="queued", uploaded_by=p.user.id)
    p.session.add(doc)
    await p.session.flush()
    await queue.enqueue(p.session, org_id=p.org_id, kind="ingest_document", payload={"document_id": str(doc.id)},
                        idempotency_key=f"ingest:{doc.id}:{doc.version}")
    await queue.wake_worker(state.redis)
    await audit.record(p.session, action="document.uploaded", org_id=p.org_id, actor=p.user.id, resource_type="document",
                       resource_id=doc.id, ip=p.ip, size=len(data), type=kind)
    return _view(doc)


@router.get("")
async def list_documents(p: Annotated[Principal, Depends(require(P.DOCS_READ))], limit: int = 25, cursor: str | None = None):
    r = await page(p.session, select(Document).where(Document.deleted_at.is_(None)), Document, limit, cursor)
    return {"items": [_view(d) for d in r["items"]], "next_cursor": r["next_cursor"]}


async def _get(p: Principal, doc_id: UUID) -> Document:
    d = (await p.session.execute(select(Document).where(Document.id == doc_id, Document.deleted_at.is_(None)))).scalar_one_or_none()
    if d is None:
        raise NotFound("Document not found")
    return d


@router.get("/{doc_id}")
async def get_document(doc_id: UUID, p: Annotated[Principal, Depends(require(P.DOCS_READ))]):
    d = await _get(p, doc_id)
    n = (await p.session.execute(select(func.count()).select_from(DocumentChunk).where(DocumentChunk.document_id == d.id))).scalar_one()
    return {**_view(d), "chunk_count": n}


@router.post("/{doc_id}/reprocess", status_code=202)
async def reprocess(doc_id: UUID, p: Annotated[Principal, Depends(require(P.DOCS_WRITE))], state: Annotated[AppState, Depends(get_state)]):
    d = await _get(p, doc_id)
    d.version += 1
    d.status, d.error = "queued", None
    await p.session.flush()
    await queue.enqueue(p.session, org_id=p.org_id, kind="ingest_document", payload={"document_id": str(d.id)},
                        idempotency_key=f"ingest:{d.id}:{d.version}")
    await queue.wake_worker(state.redis)
    await audit.record(p.session, action="document.reprocess", org_id=p.org_id, actor=p.user.id, resource_type="document", resource_id=d.id, ip=p.ip)
    return _view(d)


@router.delete("/{doc_id}", status_code=204)
async def delete_document(doc_id: UUID, p: Annotated[Principal, Depends(require(P.DOCS_DELETE))], state: Annotated[AppState, Depends(get_state)]):
    """Deletion propagates to derived data: chunks (search), imported commitments/tasks, then insights are re-evaluated."""
    d = await _get(p, doc_id)
    await p.session.execute(delete(DocumentChunk).where(DocumentChunk.document_id == d.id))
    await p.session.execute(delete(Commitment).where(Commitment.source_document_id == d.id))
    await p.session.execute(delete(Task).where(Task.source_document_id == d.id, Task.origin == "imported"))
    d.deleted_at = func.now()
    d.status = "deleted"
    try:
        await TenantStorage(state.storage, p.org_id).delete(d.storage_key)
    except StorageError:
        pass  # DB state is authoritative; an orphaned object is reaped by the lifecycle job (see ops docs)
    await queue.enqueue(p.session, org_id=p.org_id, kind="analyze", payload={}, idempotency_key=f"analyze:del:{d.id}")
    await queue.wake_worker(state.redis)
    await audit.record(p.session, action="document.deleted", org_id=p.org_id, actor=p.user.id, resource_type="document", resource_id=d.id, ip=p.ip)


