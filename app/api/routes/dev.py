"""app/api/routes/dev.py — dev-only vector search. Mounted only when APP_ENV=development."""

from fastapi import APIRouter, HTTPException, Query

from app.db.connection import get_pool
from app.llm.models import MissingApiKeyError
from app.retrieval.search import search
from app.schemas.search import SearchHit, SourceType

router = APIRouter(prefix="/dev", tags=["dev"])


@router.get("/search", response_model=list[SearchHit])
async def dev_search(
    q: str = Query(min_length=1),
    source_type: SourceType = Query(),
    k: int = Query(5, ge=1, le=50),
) -> list[SearchHit]:
    try:
        pool = get_pool()
        async with pool.connection() as conn:
            return await search(conn, q, source_type, k)
    except (RuntimeError, MissingApiKeyError) as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
