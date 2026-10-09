from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_user
from app.core.config import Settings, get_settings
from app.db.session import get_db
from app.knowledge.case_drafting import (
    CaseDraftError,
    approve_case_draft,
    generate_ai_assisted_polish,
    withdraw_case,
)
from app.models.classroom import (
    User,
)
from app.models.knowledge import KnowledgeCase, KnowledgeCaseDraft
from app.schemas.knowledge_case import (
    CaseWithdrawRequest,
    KnowledgeCaseDraftApproveRequest,
    KnowledgeCaseDraftResponse,
    KnowledgeCaseResponse,
)
from app.services.auth import current_actor, user_access
from app.services.knowledge_authorization import reviewable_case_drafts

router = APIRouter(prefix="/knowledge", tags=["knowledge"])
DatabaseSession = Annotated[Session, Depends(get_db)]
CurrentUser = Annotated[User, Depends(get_current_user)]
AppSettings = Annotated[Settings, Depends(get_settings)]


def _require_case_reviewer(db: Session, actor: User) -> set[str]:
    roles, _ = user_access(db, actor.id)
    if not {"teacher", "formal_approver"}.intersection(roles):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "KNOWLEDGE_CASE_REVIEW_ROLE_DENIED",
                "message": "Teacher or formal_approver role is required",
            },
        )
    return set(roles)


_reviewable_case_drafts = reviewable_case_drafts


def _require_case_scope(db: Session, actor: User, roles: set[str], draft_id: str) -> None:
    if (
        db.scalar(_reviewable_case_drafts(actor, roles).where(KnowledgeCaseDraft.id == draft_id))
        is None
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "KNOWLEDGE_CASE_SCOPE_DENIED",
                "message": "The case draft is outside the current user's scope",
            },
        )


def _recheck_case_access(db: Session, actor: User, draft_id: str) -> None:
    db.refresh(actor)
    if not actor.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="reviewer is inactive")
    roles = _require_case_reviewer(db, actor)
    _require_case_scope(db, actor, roles, draft_id)


def _draft_response(item: KnowledgeCaseDraft) -> KnowledgeCaseDraftResponse:
    return KnowledgeCaseDraftResponse(
        id=item.id,
        version_no=item.version_no,
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
    roles = _require_case_reviewer(db, actor)
    drafts = db.scalars(
        _reviewable_case_drafts(actor, roles)
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
    roles = _require_case_reviewer(db, actor)
    draft = db.get(KnowledgeCaseDraft, draft_id)
    if draft is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="case draft not found")
    _require_case_scope(db, actor, roles, draft.id)
    try:
        polished = generate_ai_assisted_polish(
            db,
            draft,
            settings,
            recheck_access=lambda: _recheck_case_access(db, actor, draft_id),
            actor_context=current_actor(actor),
        )
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
    roles = _require_case_reviewer(db, actor)
    draft = db.get(KnowledgeCaseDraft, draft_id)
    if draft is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="case draft not found")
    _require_case_scope(db, actor, roles, draft.id)
    try:
        case = approve_case_draft(
            db,
            draft,
            case_id=payload.case_id,
            reviewer_ref=actor.id,
            actor_context=current_actor(actor),
            confirmed_root_cause=payload.confirmed_root_cause,
            final_solution_steps=payload.final_solution_steps,
            confirmation_note=payload.confirmation_note,
            confirmation_material=(
                payload.confirmation_material.model_dump()
                if payload.confirmation_material
                else None
            ),
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


def _recheck_withdraw_access(db, actor, case):
    db.refresh(actor)
    if not actor.is_active:
        raise HTTPException(status_code=403, detail="reviewer is inactive")
    roles = _require_case_reviewer(db, actor)
    if case.source_draft_id:
        _require_case_scope(db, actor, roles, case.source_draft_id)
    elif "formal_approver" not in roles:
        raise HTTPException(status_code=403, detail="global case review authority was revoked")


@router.post("/cases/{case_id}/withdraw")
def withdraw_knowledge_case(
    case_id: str, payload: CaseWithdrawRequest, actor: CurrentUser, db: DatabaseSession
):
    roles = _require_case_reviewer(db, actor)
    case = db.get(KnowledgeCase, case_id)
    if case is None:
        raise HTTPException(status_code=404, detail="case not found")
    if case.source_draft_id:
        _require_case_scope(db, actor, roles, case.source_draft_id)
    elif "formal_approver" not in roles:
        raise HTTPException(status_code=403, detail="global cases require formal review authority")
    try:
        return withdraw_case(
            db,
            case,
            actor,
            request_id=str(payload.request_id),
            expected_version=payload.expected_version,
            reason=payload.reason,
            recheck_access=lambda: _recheck_withdraw_access(db, actor, case),
        )
    except CaseDraftError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
