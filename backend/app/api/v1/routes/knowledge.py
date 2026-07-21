from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.dependencies import require_review_access
from app.core.config import Settings, get_settings
from app.db.session import get_db
from app.schemas.knowledge import (
    KnowledgeDocumentResponse,
    KnowledgeEmbeddingUpsertRequest,
    KnowledgeEmbeddingUpsertResponse,
    KnowledgeReviewRequest,
    KnowledgeReviewResponse,
    KnowledgeSearchRequest,
    KnowledgeSearchResponse,
    KnowledgeSourceCreate,
    KnowledgeSourceResponse,
    KnowledgeStatusResponse,
    KnowledgeTextImportRequest,
)
from app.services.knowledge import (
    KnowledgeServiceError,
    create_source,
    get_knowledge_status,
    import_text_document,
    list_sources,
    review_document,
    search_knowledge,
    upsert_embeddings,
)

router = APIRouter(prefix="/knowledge", tags=["knowledge"])
DatabaseSession = Annotated[Session, Depends(get_db)]
ReviewAccess = Annotated[None, Depends(require_review_access)]
AppSettings = Annotated[Settings, Depends(get_settings)]


def _raise_http_error(exc: KnowledgeServiceError) -> None:
    raise HTTPException(
        status_code=exc.status_code,
        detail={"code": exc.code, "message": exc.message},
    ) from exc


@router.get("/status", response_model=KnowledgeStatusResponse)
def read_knowledge_status(
    _: ReviewAccess, db: DatabaseSession, settings: AppSettings
) -> KnowledgeStatusResponse:
    return get_knowledge_status(db, settings)


@router.get("/sources", response_model=list[KnowledgeSourceResponse])
def read_knowledge_sources(_: ReviewAccess, db: DatabaseSession) -> list[KnowledgeSourceResponse]:
    return list_sources(db)


@router.post(
    "/sources", response_model=KnowledgeSourceResponse, status_code=status.HTTP_201_CREATED
)
def register_knowledge_source(
    payload: KnowledgeSourceCreate, _: ReviewAccess, db: DatabaseSession
) -> KnowledgeSourceResponse:
    try:
        return create_source(db, payload)
    except KnowledgeServiceError as exc:
        _raise_http_error(exc)


@router.post(
    "/sources/{source_id}/documents/text",
    response_model=KnowledgeDocumentResponse,
    status_code=status.HTTP_201_CREATED,
)
def import_knowledge_text(
    source_id: str,
    payload: KnowledgeTextImportRequest,
    _: ReviewAccess,
    db: DatabaseSession,
    settings: AppSettings,
) -> KnowledgeDocumentResponse:
    try:
        return import_text_document(db, source_id, payload, settings)
    except KnowledgeServiceError as exc:
        _raise_http_error(exc)


@router.patch("/documents/{document_id}/review", response_model=KnowledgeReviewResponse)
def review_knowledge_document(
    document_id: str,
    payload: KnowledgeReviewRequest,
    _: ReviewAccess,
    db: DatabaseSession,
) -> KnowledgeReviewResponse:
    try:
        return review_document(db, document_id, payload)
    except KnowledgeServiceError as exc:
        _raise_http_error(exc)


@router.post(
    "/documents/{document_id}/embeddings",
    response_model=KnowledgeEmbeddingUpsertResponse,
)
def store_knowledge_embeddings(
    document_id: str,
    payload: KnowledgeEmbeddingUpsertRequest,
    _: ReviewAccess,
    db: DatabaseSession,
    settings: AppSettings,
) -> KnowledgeEmbeddingUpsertResponse:
    try:
        return upsert_embeddings(db, document_id, payload, settings)
    except KnowledgeServiceError as exc:
        _raise_http_error(exc)


@router.post("/search", response_model=KnowledgeSearchResponse)
def search_approved_knowledge(
    payload: KnowledgeSearchRequest,
    _: ReviewAccess,
    db: DatabaseSession,
) -> KnowledgeSearchResponse:
    try:
        return search_knowledge(db, payload)
    except KnowledgeServiceError as exc:
        _raise_http_error(exc)
