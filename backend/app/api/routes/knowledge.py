from dataclasses import asdict

from fastapi import APIRouter

from app.api.dependencies import CurrentUser, DbSession
from app.core.errors import AppError
from app.rag.retrieval import RetrievalError, search_knowledge
from app.schemas.knowledge import (
    KnowledgeCitationOut,
    KnowledgeSearchRequest,
    KnowledgeSearchResponse,
)

router = APIRouter(prefix="/knowledge", tags=["医学知识库"])


@router.post("/search", response_model=KnowledgeSearchResponse)
async def search_medical_knowledge(
    payload: KnowledgeSearchRequest,
    user: CurrentUser,
    db: DbSession,
):
    try:
        result = await search_knowledge(db, payload.query, top_k=payload.top_k)
    except RetrievalError as exc:
        raise AppError(exc.status_code, exc.code, str(exc)) from exc
    return KnowledgeSearchResponse(
        query_redacted=result.query_redacted,
        embedding_model=result.model,
        embedding_version=result.version,
        items=[KnowledgeCitationOut(**asdict(item)) for item in result.items],
    )
