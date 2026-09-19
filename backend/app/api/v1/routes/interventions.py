import csv
import io
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_user, require_permission
from app.db.session import get_db
from app.models.base import utc_now
from app.models.classroom import (
    AuditEvent,
    ExperimentAssignment,
    TeachingAssignment,
    User,
)
from app.models.diagnosis_result import DiagnosisResult
from app.models.intervention import (
    ClassroomMessage,
    InterventionCase,
)
from app.schemas.intervention import (
    ClassroomMessageCreate,
    ClassroomMessageResponse,
    InterventionActionRequest,
    InterventionCaseResponse,
    InterventionTimelineItem,
    ProblemResolutionRequest,
)
from app.services.auth import user_access
from app.services.data_scope import (
    ScopeConflict,
    ScopeViolation,
    assert_student_session_access,
    diagnosis_session,
    teacher_has_class_access,
)
from app.services.interventions import (
    InterventionConflict,
    apply_action,
    apply_problem_resolution,
    ensure_intervention_case,
    public_resolution_summary,
    timeline,
)

router = APIRouter(prefix="/teacher-workflow", tags=["teacher-workflow"])
DatabaseSession = Annotated[Session, Depends(get_db)]
InterventionManager = Annotated[User, Depends(require_permission("intervention.manage"))]
CurrentUser = Annotated[User, Depends(get_current_user)]


def _case_response(db: Session, actor: User, case: InterventionCase) -> InterventionCaseResponse:
    _assert_case_access(db, actor, case, allow_student=True)
    summary = (
        case.resolution_summary
        if _teacher_has_class_access(db, actor, case.class_id)
        else public_resolution_summary(db, case)
    )
    return InterventionCaseResponse(
        id=case.id,
        diagnosis_result_id=case.diagnosis_result_id,
        episode_id=case.episode_id,
        class_id=case.class_id,
        assigned_teacher_user_id=case.assigned_teacher_user_id,
        status=case.status,
        version_no=case.version_no,
        resolution_summary=summary,
        is_test_data=case.is_test_data,
    )


def _roles(db: Session, actor: User) -> set[str]:
    roles, _ = user_access(db, actor.id)
    return set(roles)


def _teacher_has_class_access(db, actor, class_id):
    return teacher_has_class_access(db, actor, class_id)


def _assert_teacher_class_access(
    db: Session,
    actor: Optional[User],
    class_id: Optional[str],
) -> None:
    if class_id is None or not _teacher_has_class_access(db, actor, class_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "CLASS_SCOPE_DENIED",
                "message": "The class is outside the current user's scope",
            },
        )


def _accessible_class_for_diagnosis(db: Session, actor: User, diagnosis: DiagnosisResult) -> str:
    owner = diagnosis_session(db, diagnosis)
    if owner is not None:
        assignment = db.get(ExperimentAssignment, owner.experiment_assignment_id)
        if _teacher_has_class_access(db, actor, assignment.class_id):
            return assignment.class_id
        try:
            assert_student_session_access(db, actor, owner)
            return assignment.class_id
        except (ScopeConflict, ScopeViolation):
            pass
    raise HTTPException(status_code=403, detail="diagnosis recorded scope is not accessible")


def _assert_case_access(db, actor, case, *, allow_student):
    diagnosis = db.get(DiagnosisResult, case.diagnosis_result_id)
    owner = diagnosis_session(db, diagnosis) if diagnosis is not None else None
    if owner is not None:
        assignment = db.get(ExperimentAssignment, owner.experiment_assignment_id)
        if assignment.class_id != case.class_id:
            raise HTTPException(status_code=403, detail="intervention recorded scope conflicts")
    if _teacher_has_class_access(db, actor, case.class_id):
        return
    if allow_student and owner is not None:
        try:
            assert_student_session_access(db, actor, owner)
            return
        except (ScopeConflict, ScopeViolation):
            pass
    raise HTTPException(status_code=403, detail="intervention recorded scope is not accessible")


@router.post(
    "/diagnoses/{diagnosis_id}/intervention",
    response_model=InterventionCaseResponse,
    status_code=status.HTTP_201_CREATED,
)
def open_intervention(
    diagnosis_id: str,
    actor: CurrentUser,
    db: DatabaseSession,
    episode_id: Optional[str] = None,
) -> InterventionCaseResponse:
    diagnosis = db.get(DiagnosisResult, diagnosis_id)
    if diagnosis is None:
        raise HTTPException(status_code=404, detail="diagnosis not found")
    class_id = _accessible_class_for_diagnosis(db, actor, diagnosis)
    try:
        case = ensure_intervention_case(
            db,
            diagnosis,
            class_id=class_id,
            actor_user_id=actor.id,
            source="authenticated_user_request",
            episode_id=episode_id,
        )
        _assert_case_access(db, actor, case, allow_student=True)
        db.commit()
    except InterventionConflict as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except IntegrityError:
        db.rollback()
        # Re-resolve the actual winning object and reapply all access checks.
        case = ensure_intervention_case(
            db,
            diagnosis,
            class_id=class_id,
            actor_user_id=actor.id,
            source="authenticated_user_request",
            episode_id=episode_id,
        )
    if case is None:
        raise HTTPException(status_code=409, detail="intervention creation conflict")
    return _case_response(db, actor, case)


@router.get("/interventions", response_model=list[InterventionCaseResponse])
def intervention_queue(
    actor: InterventionManager,
    db: DatabaseSession,
) -> list[InterventionCaseResponse]:
    roles = _roles(db, actor)
    query = select(InterventionCase).order_by(InterventionCase.created_at)
    if "admin" not in roles:
        query = query.join(
            TeachingAssignment,
            TeachingAssignment.class_id == InterventionCase.class_id,
        ).where(TeachingAssignment.user_id == actor.id)
    results = []
    for case in db.scalars(query):
        try:
            results.append(_case_response(db, actor, case))
        except HTTPException as exc:
            if exc.status_code != 403:
                raise
    return results


@router.post("/interventions/{case_id}/problem-resolution")
def resolve_intervention_problem(
    case_id: str, payload: ProblemResolutionRequest, actor: InterventionManager, db: DatabaseSession
):
    case = db.get(InterventionCase, case_id)
    if case is None:
        raise HTTPException(status_code=404, detail="intervention not found")
    _assert_case_access(db, actor, case, allow_student=False)
    try:
        return apply_problem_resolution(
            db,
            case,
            actor,
            request_id=str(payload.request_id),
            expected_revision=payload.expected_revision,
            recovery_diagnosis_id=str(payload.recovery_diagnosis_id)
            if payload.recovery_diagnosis_id
            else None,
        )
    except InterventionConflict as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get(
    "/interventions/{case_id}",
    response_model=InterventionCaseResponse,
)
def read_intervention(
    case_id: str,
    actor: CurrentUser,
    db: DatabaseSession,
) -> InterventionCaseResponse:
    case = db.get(InterventionCase, case_id)
    if case is None:
        raise HTTPException(status_code=404, detail="intervention not found")
    _assert_case_access(db, actor, case, allow_student=True)
    response = _case_response(db, actor, case)
    if not _teacher_has_class_access(db, actor, case.class_id):
        response.resolution_summary = public_resolution_summary(db, case)
    return response


@router.post(
    "/interventions/{case_id}/actions",
    response_model=InterventionCaseResponse,
)
def act_on_intervention(
    case_id: str,
    payload: InterventionActionRequest,
    actor: InterventionManager,
    db: DatabaseSession,
) -> InterventionCaseResponse:
    case = db.get(InterventionCase, case_id)
    if case is None:
        raise HTTPException(status_code=404, detail="intervention not found")
    _assert_case_access(db, actor, case, allow_student=False)
    if payload.action == "transfer" and payload.target_teacher_user_id:
        _assert_teacher_class_access(
            db,
            db.get(User, payload.target_teacher_user_id),
            case.class_id,
        )
    try:
        updated = apply_action(
            db,
            case,
            actor,
            request_id=str(payload.request_id) if payload.request_id else None,
            action=payload.action,
            expected_version=payload.expected_version,
            note=payload.note,
            target_teacher_user_id=payload.target_teacher_user_id,
            is_private=payload.is_private,
        )
    except InterventionConflict as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    return _case_response(db, actor, updated)


@router.get(
    "/interventions/{case_id}/timeline",
    response_model=list[InterventionTimelineItem],
)
def intervention_timeline(
    case_id: str,
    actor: InterventionManager,
    db: DatabaseSession,
) -> list[InterventionTimelineItem]:
    case = db.get(InterventionCase, case_id)
    if case is None:
        raise HTTPException(status_code=404, detail="intervention not found")
    _assert_case_access(db, actor, case, allow_student=False)
    return [
        InterventionTimelineItem(
            action=item.action,
            actor_user_id=item.actor_user_id,
            from_status=item.from_status,
            to_status=item.to_status,
            note=item.note,
            is_private=item.is_private,
            metadata=item.metadata_json,
            created_at=item.created_at.isoformat(),
        )
        for item in timeline(db, case_id, include_private=True)
    ]


@router.post("/messages", response_model=ClassroomMessageResponse, status_code=201)
def publish_message(
    payload: ClassroomMessageCreate,
    actor: InterventionManager,
    db: DatabaseSession,
) -> ClassroomMessageResponse:
    _assert_teacher_class_access(db, actor, payload.class_id)
    message = ClassroomMessage(
        class_id=payload.class_id,
        author_user_id=actor.id,
        message=payload.message,
        audience=payload.audience,
        is_test_data=payload.is_test_data,
    )
    db.add(message)
    db.commit()
    db.refresh(message)
    return ClassroomMessageResponse(
        id=message.id,
        class_id=message.class_id,
        message=message.message,
        audience=message.audience,
        retracted=False,
        is_test_data=message.is_test_data,
    )


@router.delete("/messages/{message_id}", response_model=ClassroomMessageResponse)
def retract_message(
    message_id: str,
    actor: InterventionManager,
    db: DatabaseSession,
) -> ClassroomMessageResponse:
    message = db.get(ClassroomMessage, message_id)
    if message is None:
        raise HTTPException(status_code=404, detail="message not found")
    _assert_teacher_class_access(db, actor, message.class_id)
    if message.retracted_at is None:
        message.retracted_at = utc_now()
        message.retracted_by_user_id = actor.id
        db.commit()
    return ClassroomMessageResponse(
        id=message.id,
        class_id=message.class_id,
        message=message.message,
        audience=message.audience,
        retracted=True,
        is_test_data=message.is_test_data,
    )


@router.get("/classes/{class_id}/report.csv")
def export_class_report(
    class_id: str,
    actor: InterventionManager,
    db: DatabaseSession,
) -> Response:
    _assert_teacher_class_access(db, actor, class_id)
    cases = list(
        db.scalars(
            select(InterventionCase)
            .where(InterventionCase.class_id == class_id)
            .order_by(InterventionCase.created_at)
        )
    )
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["case_id", "diagnosis_result_id", "status", "assigned_teacher", "test_data"])
    for case in cases:
        writer.writerow(
            [
                case.id,
                case.diagnosis_result_id,
                case.status,
                case.assigned_teacher_user_id or "",
                str(case.is_test_data).lower(),
            ]
        )
    db.add(
        AuditEvent(
            actor_user_id=actor.id,
            action="classroom.report_export",
            resource_type="class",
            resource_id=class_id,
            details_json={"format": "csv", "row_count": len(cases)},
            is_test_data=all(case.is_test_data for case in cases) if cases else False,
            created_at=utc_now(),
        )
    )
    db.commit()
    return Response(
        content=output.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="class-{class_id}-report.csv"'},
    )
