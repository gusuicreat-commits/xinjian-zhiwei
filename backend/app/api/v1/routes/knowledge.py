from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_user, require_review_access
from app.core.config import Settings, get_settings
from app.db.session import get_db
from app.models.classroom import User
from app.schemas.knowledge import (
    KnowledgeChunkMergeRequest,
    KnowledgeChunkSplitRequest,
    KnowledgeChunkUpdate,
    KnowledgeDocumentResponse,
    KnowledgeEmbeddingUpsertRequest,
    KnowledgeEmbeddingUpsertResponse,
    KnowledgeFileImportRequest,
    KnowledgeReviewRequest,
    KnowledgeReviewResponse,
    KnowledgeSearchRequest,
    KnowledgeSearchResponse,
    KnowledgeSourceCreate,
    KnowledgeSourceResponse,
    KnowledgeStatusResponse,
    KnowledgeTextImportRequest,
    KnowledgeWorkspaceResponse,
)
from app.services.auth import user_access
from app.services.knowledge import (
    KnowledgeServiceError,
    create_source,
    delete_chunk,
    get_document_workspace,
    get_knowledge_status,
    import_text_document,
    list_sources,
    merge_chunks,
    review_document,
    search_knowledge,
    split_chunk_at,
    update_chunk,
    upsert_embeddings,
)
from app.services.knowledge_files import decode_and_extract

router = APIRouter(prefix="/knowledge", tags=["knowledge"])
DatabaseSession = Annotated[Session, Depends(get_db)]
ReviewAccess = Annotated[None, Depends(require_review_access)]
CurrentUser = Annotated[User, Depends(get_current_user)]
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


@router.post(
    "/sources/{source_id}/documents/file",
    response_model=KnowledgeDocumentResponse,
    status_code=status.HTTP_201_CREATED,
)
def import_knowledge_file(
    source_id: str,
    payload: KnowledgeFileImportRequest,
    _: ReviewAccess,
    db: DatabaseSession,
    settings: AppSettings,
) -> KnowledgeDocumentResponse:
    try:
        content, parser_name = decode_and_extract(
            payload.filename,
            payload.content_base64,
            settings.knowledge_max_file_bytes,
        )
        extracted = KnowledgeTextImportRequest(
            title=payload.filename,
            content=content,
            media_type=payload.media_type,
            language=payload.language,
            storage_uri=payload.storage_uri,
            parser_name=parser_name,
            parser_version="1",
            locator_prefix=payload.locator_prefix,
            metadata=payload.metadata,
            organizer_ref=payload.organizer_ref,
            content_origin=payload.content_origin,
            is_test_data=payload.is_test_data,
        )
        return import_text_document(db, source_id, extracted, settings)
    except KnowledgeServiceError as exc:
        _raise_http_error(exc)


@router.get(
    "/documents/{document_id}/workspace",
    response_model=KnowledgeWorkspaceResponse,
)
def read_document_workspace(
    document_id: str,
    _: ReviewAccess,
    db: DatabaseSession,
) -> KnowledgeWorkspaceResponse:
    try:
        return get_document_workspace(db, document_id)
    except KnowledgeServiceError as exc:
        _raise_http_error(exc)


@router.patch("/chunks/{chunk_id}", response_model=KnowledgeWorkspaceResponse)
def edit_knowledge_chunk(
    chunk_id: str,
    payload: KnowledgeChunkUpdate,
    _: ReviewAccess,
    db: DatabaseSession,
) -> KnowledgeWorkspaceResponse:
    try:
        return update_chunk(
            db,
            chunk_id,
            content=payload.content,
            metadata=payload.metadata,
        )
    except KnowledgeServiceError as exc:
        _raise_http_error(exc)


@router.post("/chunks/{chunk_id}/split", response_model=KnowledgeWorkspaceResponse)
def split_knowledge_chunk(
    chunk_id: str,
    payload: KnowledgeChunkSplitRequest,
    _: ReviewAccess,
    db: DatabaseSession,
) -> KnowledgeWorkspaceResponse:
    try:
        return split_chunk_at(db, chunk_id, payload.offset)
    except KnowledgeServiceError as exc:
        _raise_http_error(exc)


@router.post("/chunks/merge", response_model=KnowledgeWorkspaceResponse)
def merge_knowledge_chunks(
    payload: KnowledgeChunkMergeRequest,
    _: ReviewAccess,
    db: DatabaseSession,
) -> KnowledgeWorkspaceResponse:
    try:
        return merge_chunks(db, payload.chunk_ids)
    except KnowledgeServiceError as exc:
        _raise_http_error(exc)


@router.delete("/chunks/{chunk_id}", response_model=KnowledgeWorkspaceResponse)
def remove_knowledge_chunk(
    chunk_id: str,
    _: ReviewAccess,
    db: DatabaseSession,
) -> KnowledgeWorkspaceResponse:
    try:
        return delete_chunk(db, chunk_id)
    except KnowledgeServiceError as exc:
        _raise_http_error(exc)


@router.patch("/documents/{document_id}/review", response_model=KnowledgeReviewResponse)
def review_knowledge_document(
    document_id: str,
    payload: KnowledgeReviewRequest,
    actor: CurrentUser,
    db: DatabaseSession,
) -> KnowledgeReviewResponse:
    required_role = {
        "organizer": "knowledge_organizer",
        "technical_reviewer": "technical_reviewer",
        "formal_approver": "formal_approver",
    }[payload.reviewer_role]
    roles, _ = user_access(db, actor.id)
    if required_role not in roles:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "KNOWLEDGE_REVIEW_ROLE_DENIED",
                "message": f"Role {required_role} is required",
            },
        )
    authenticated_payload = payload.model_copy(
        update={"reviewer_ref": actor.id}
    )
    try:
        return review_document(db, document_id, authenticated_payload)
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
