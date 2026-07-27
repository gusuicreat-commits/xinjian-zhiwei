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
    DeviceBinding,
    TeachingAssignment,
    User,
)
from app.models.diagnosis_result import DiagnosisResult
from app.models.intervention import (
    ClassroomMessage,
    InterventionCase,
    InterventionEvent,
)
from app.schemas.intervention import (
    ClassroomMessageCreate,
    ClassroomMessageResponse,
    InterventionActionRequest,
    InterventionCaseResponse,
    InterventionTimelineItem,
)
from app.services.auth import user_access
from app.services.interventions import InterventionConflict, apply_action, timeline

router = APIRouter(prefix="/teacher-workflow", tags=["teacher-workflow"])
DatabaseSession = Annotated[Session, Depends(get_db)]
InterventionManager = Annotated[User, Depends(require_permission("intervention.manage"))]
CurrentUser = Annotated[User, Depends(get_current_user)]


def _case_response(case: InterventionCase) -> InterventionCaseResponse:
    return InterventionCaseResponse(
        id=case.id,
        diagnosis_result_id=case.diagnosis_result_id,
        class_id=case.class_id,
        assigned_teacher_user_id=case.assigned_teacher_user_id,
        status=case.status,
        version_no=case.version_no,
        resolution_summary=case.resolution_summary,
        is_test_data=case.is_test_data,
    )


def _roles(db: Session, actor: User) -> set[str]:
    roles, _ = user_access(db, actor.id)
    return set(roles)


def _teacher_has_class_access(
    db: Session,
    actor: Optional[User],
    class_id: str,
) -> bool:
    if actor is None:
        return False
    roles = _roles(db, actor)
    if "admin" in roles:
        return True
    if not roles.intersection({"teacher", "teaching_assistant"}):
        return False
    return (
        db.scalar(
            select(TeachingAssignment.id).where(
                TeachingAssignment.class_id == class_id,
                TeachingAssignment.user_id == actor.id,
            )
        )
        is not None
    )


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


def _accessible_binding_for_diagnosis(
    db: Session,
    actor: User,
    diagnosis: DiagnosisResult,
) -> DeviceBinding:
    roles = _roles(db, actor)
    query = select(DeviceBinding).where(
        DeviceBinding.device_id == diagnosis.device_id,
        DeviceBinding.is_active.is_(True),
    )
    if "admin" in roles:
        binding = db.scalar(query.order_by(DeviceBinding.created_at))
    elif roles.intersection({"teacher", "teaching_assistant"}):
        binding = db.scalar(
            query.join(
                TeachingAssignment,
                TeachingAssignment.class_id == DeviceBinding.class_id,
            ).where(TeachingAssignment.user_id == actor.id)
        )
    elif "student" in roles:
        binding = db.scalar(query.where(DeviceBinding.student_user_id == actor.id))
    else:
        binding = None
    if binding is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "DIAGNOSIS_SCOPE_DENIED",
                "message": "The diagnosis is outside the current user's scope",
            },
        )
    return binding


def _assert_case_access(
    db: Session,
    actor: User,
    case: InterventionCase,
    *,
    allow_student: bool,
) -> None:
    roles = _roles(db, actor)
    if "admin" in roles:
        return
    if roles.intersection({"teacher", "teaching_assistant"}):
        _assert_teacher_class_access(db, actor, case.class_id)
        return
    if allow_student and "student" in roles:
        diagnosis = db.get(DiagnosisResult, case.diagnosis_result_id)
        if diagnosis is not None:
            binding = db.scalar(
                select(DeviceBinding.id).where(
                    DeviceBinding.device_id == diagnosis.device_id,
                    DeviceBinding.class_id == case.class_id,
                    DeviceBinding.student_user_id == actor.id,
                    DeviceBinding.is_active.is_(True),
                )
            )
            if binding is not None:
                return
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail={
            "code": "INTERVENTION_SCOPE_DENIED",
            "message": "The intervention is outside the current user's scope",
        },
    )


@router.post(
    "/diagnoses/{diagnosis_id}/intervention",
    response_model=InterventionCaseResponse,
    status_code=status.HTTP_201_CREATED,
)
def open_intervention(
    diagnosis_id: str,
    actor: CurrentUser,
    db: DatabaseSession,
) -> InterventionCaseResponse:
    diagnosis = db.get(DiagnosisResult, diagnosis_id)
    if diagnosis is None:
        raise HTTPException(status_code=404, detail="diagnosis not found")
    binding = _accessible_binding_for_diagnosis(db, actor, diagnosis)
    existing = db.scalar(
        select(InterventionCase).where(InterventionCase.diagnosis_result_id == diagnosis_id)
    )
    if existing is not None:
        return _case_response(existing)
    case = InterventionCase(
        diagnosis_result_id=diagnosis_id,
        class_id=binding.class_id,
        status="open",
        version_no=1,
        is_test_data=diagnosis.is_test_data,
    )
    db.add(case)
    db.flush()
    db.add(
        InterventionEvent(
            case_id=case.id,
            actor_user_id=actor.id,
            action="request_help",
            from_status=None,
            to_status="open",
            note=None,
            is_private=False,
            metadata_json={"diagnosis_result_id": diagnosis_id},
            created_at=utc_now(),
        )
    )
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        case = db.scalar(
            select(InterventionCase).where(
                InterventionCase.diagnosis_result_id == diagnosis_id
            )
        )
    if case is None:
        raise HTTPException(status_code=409, detail="intervention creation conflict")
    return _case_response(case)


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
    return [_case_response(case) for case in db.scalars(query)]


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
    return _case_response(case)


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
    return _case_response(updated)


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
