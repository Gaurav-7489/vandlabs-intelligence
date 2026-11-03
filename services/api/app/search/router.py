from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select

from app.core.state import AppState, get_state
from app.identity.deps import Principal, require
from app.identity.permissions import P
from app.models import Document, DocumentChunk

router = APIRouter(tags=["search"])


async def search_chunks(session, q: str, limit: int) -> list[dict]:
    tsq = func.websearch_to_tsquery("english", q)  # safe parser: no tsquery syntax errors from user input
    stmt = (select(DocumentChunk.id, DocumentChunk.document_id, DocumentChunk.locator, DocumentChunk.text,
                   func.ts_rank(DocumentChunk.tsv, tsq).label("rank"), Document.filename, Document.created_at)
            .join(Document, Document.id == DocumentChunk.document_id)
            .where(DocumentChunk.tsv.op("@@")(tsq), Document.deleted_at.is_(None))
            .order_by(func.ts_rank(DocumentChunk.tsv, tsq).desc(), DocumentChunk.id).limit(limit))
    return [{"chunk_id": r.id, "document_id": r.document_id, "filename": r.filename, "locator": r.locator,
             "text": r.text, "score": float(r.rank), "document_uploaded_at": r.created_at}
            for r in (await session.execute(stmt)).all()]


@router.get("/search")
async def search(q: Annotated[str, Query(min_length=2, max_length=200)], p: Annotated[Principal, Depends(require(P.SEARCH))],
                 state: Annotated[AppState, Depends(get_state)], limit: Annotated[int, Query(ge=1, le=25)] = 10):
    await state.limiter.hit("search", f"user:{p.user.id}")
    return {"query": q, "mode": "keyword", "items": await search_chunks(p.session, q, limit)}
