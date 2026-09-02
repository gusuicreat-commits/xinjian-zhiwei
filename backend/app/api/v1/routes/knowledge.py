from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_user, require_review_access
from app.core.config import Settings, get_settings
from app.db.session import get_db
from app.knowledge.case_drafting import (
    CaseDraftError,
    approve_case_draft,
    generate_ai_assisted_polish,
)
from app.models.classroom import User
from app.models.knowledge import KnowledgeCaseDraft
from app.schemas.knowledge import (
    KnowledgeChunkMergeRequest,
    KnowledgeChunkSplitRequest,
    KnowledgeChunkUpdate,
    KnowledgeDocumentResponse,
    KnowledgeFileImportRequest,
    KnowledgeReviewRequest,
    KnowledgeReviewResponse,
    KnowledgeSourceCreate,
    KnowledgeSourceResponse,
    KnowledgeStatusResponse,
    KnowledgeTextImportRequest,
    KnowledgeWorkspaceResponse,
)
from app.schemas.knowledge_case import (
    KnowledgeCaseDraftApproveRequest,
    KnowledgeCaseDraftResponse,
    KnowledgeCaseResponse,
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
    split_chunk_at,
    update_chunk,
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


def _require_case_reviewer(db: Session, actor: User) -> None:
    roles, _ = user_access(db, actor.id)
    if not {"teacher", "formal_approver"}.intersection(roles):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "KNOWLEDGE_CASE_REVIEW_ROLE_DENIED",
                "message": "Teacher or formal_approver role is required",
            },
        )


def _draft_response(item: KnowledgeCaseDraft) -> KnowledgeCaseDraftResponse:
    return KnowledgeCaseDraftResponse(
        id=item.id,
        diagnosis_result_id=item.diagnosis_result_id,
        feedback_id=item.feedback_id,
        experiment_type=item.experiment_type,
        error_type=item.error_type,
        fact_snapshot=item.fact_snapshot,
        template_payload=item.template_payload,
        polished_payload=item.polished_payload,
        quality_checks=item.quality_checks,
        root_cause=item.root_cause,
        solution_record=item.solution_record,
        source_ids=item.source_ids,
        allowed_ai_fields=item.allowed_ai_fields,
        facts_locked=item.facts_locked,
        ai_audit=item.ai_audit,
        status=item.status,
        reviewer_ref=item.reviewer_ref,
        reviewed_at=item.reviewed_at,
        is_test_data=item.is_test_data,
        created_at=item.created_at,
        updated_at=item.updated_at,
    )


@router.get("/case-drafts/pending", response_model=list[KnowledgeCaseDraftResponse])
def read_pending_case_drafts(
    actor: CurrentUser,
    db: DatabaseSession,
) -> list[KnowledgeCaseDraftResponse]:
    _require_case_reviewer(db, actor)
    drafts = db.scalars(
        select(KnowledgeCaseDraft)
        .where(KnowledgeCaseDraft.status == "pending_review")
        .order_by(KnowledgeCaseDraft.created_at, KnowledgeCaseDraft.id)
    ).all()
    return [_draft_response(item) for item in drafts]


@router.post(
    "/case-drafts/{draft_id}/ai-polish",
    response_model=KnowledgeCaseDraftResponse,
)
def polish_diagnosis_case_draft(
    draft_id: str,
    actor: CurrentUser,
    db: DatabaseSession,
    settings: AppSettings,
) -> KnowledgeCaseDraftResponse:
    _require_case_reviewer(db, actor)
    draft = db.get(KnowledgeCaseDraft, draft_id)
    if draft is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="case draft not found")
    try:
        polished = generate_ai_assisted_polish(db, draft, settings)
    except CaseDraftError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return _draft_response(polished)


@router.post(
    "/case-drafts/{draft_id}/approve",
    response_model=KnowledgeCaseResponse,
)
def approve_diagnosis_case_draft(
    draft_id: str,
    payload: KnowledgeCaseDraftApproveRequest,
    actor: CurrentUser,
    db: DatabaseSession,
) -> KnowledgeCaseResponse:
    _require_case_reviewer(db, actor)
    draft = db.get(KnowledgeCaseDraft, draft_id)
    if draft is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="case draft not found")
    try:
        case = approve_case_draft(
            db,
            draft,
            case_id=payload.case_id,
            reviewer_ref=actor.id,
            confirmed_root_cause=payload.confirmed_root_cause,
            final_solution_steps=payload.final_solution_steps,
            confirmation_note=payload.confirmation_note,
        )
    except CaseDraftError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return KnowledgeCaseResponse(
        id=case.id,
        experiment_type=case.experiment_type,
        error_type=case.error_type,
        symptom=case.symptom,
        normal_state=case.normal_state,
        evidence=case.evidence,
        possible_causes=case.possible_causes,
        solution_steps=case.solution_steps,
        teacher_notes=case.teacher_notes,
        facts=case.facts,
        root_cause_value=case.root_cause_value,
        root_cause_status=case.root_cause_status,
        confirmed_by=case.confirmed_by,
        confirmed_at=case.confirmed_at,
        solution_record=case.solution_record,
        ai_generated_fields=case.ai_generated_fields,
        source_type=case.source_type,
        facts_locked=case.facts_locked,
        quality_check_passed=case.quality_check_passed,
        review_status=case.review_status,
        source_ref=case.source_ref,
        version=case.version,
        is_test_data=case.is_test_data,
        created_at=case.created_at,
        updated_at=case.updated_at,
    )


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
    authenticated_payload = payload.model_copy(update={"reviewer_ref": actor.id})
    try:
        return review_document(db, document_id, authenticated_payload)
    except KnowledgeServiceError as exc:
        _raise_http_error(exc)
