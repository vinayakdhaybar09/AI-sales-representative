from fastapi import APIRouter, Response

from app.core.errors import STATUS_BY_CODE
from app.schemas.support_query import QuerySubmitEnvelope, QuerySubmitRequest
from app.services.query_service import submit_query

router = APIRouter(prefix="/api", tags=["queries"])


@router.post("/queries", response_model=QuerySubmitEnvelope)
async def create_query(request: QuerySubmitRequest, response: Response) -> QuerySubmitEnvelope:
    """Store a query raised from the in-chat form (demo: database only, no email, no image storage)."""
    envelope = await submit_query(request)
    if envelope.error is not None:
        response.status_code = STATUS_BY_CODE.get(envelope.error.code, 500)
    return envelope
