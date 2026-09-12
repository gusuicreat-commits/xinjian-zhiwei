from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.dependencies import get_authenticated_device
from app.core.config import Settings, get_settings
from app.db.session import get_db
from app.models.device import Device
from app.models.diagnosis_result import DiagnosisResult
from app.schemas.student import (
    StudentDashboardResponse,
    StudentFeedbackCreate,
    StudentFeedbackItem,
    StudentFeedbackRecoveryResponse,
    StudentSessionResponse,
)
from app.services.diagnosis_workflow import (
    WorkflowConflict,
    WorkflowScopeViolation,
    find_active_experiment_session,
)
from app.services.student_dashboard import build_student_dashboard
from app.services.student_feedback import read_feedback_recovery, submit_student_feedback

router = APIRouter(prefix="/student", tags=["student"])
AuthenticatedDevice = Annotated[Device, Depends(get_authenticated_device)]
DatabaseSession = Annotated[Session, Depends(get_db)]
AppSettings = Annotated[Settings, Depends(get_settings)]


@router.post("/session", response_model=StudentSessionResponse)
def create_student_session(
    device: AuthenticatedDevice, db: DatabaseSession
) -> StudentSessionResponse:
    try:
        experiment_session = find_active_experiment_session(db, device)
    except WorkflowConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return StudentSessionResponse(
        device_id=device.device_key,
        display_name=device.display_name,
        auth_mode="device_credential_placeholder",
        student_user_id=(experiment_session.student_user_id if experiment_session else None),
        experiment_session_id=(experiment_session.id if experiment_session else None),
        experiment_assignment_id=(
            experiment_session.experiment_assignment_id if experiment_session else None
        ),
        notice=(
            "已验证学生—实验会话—设备归属，LangGraph 诊断可用。"
            if experiment_session
            else "当前设备没有唯一有效的学生实验会话；LangGraph 诊断已关闭。"
        ),
    )


@router.get("/dashboard", response_model=StudentDashboardResponse)
def get_student_dashboard(
    device: AuthenticatedDevice, db: DatabaseSession
) -> StudentDashboardResponse:
    return build_student_dashboard(db, device)


@router.post(
    "/diagnoses/{diagnosis_result_id}/feedback",
    response_model=StudentFeedbackItem,
    status_code=status.HTTP_201_CREATED,
)
def create_student_feedback(
    diagnosis_result_id: str,
    payload: StudentFeedbackCreate,
    request: Request,
    device: AuthenticatedDevice,
    db: DatabaseSession,
    settings: AppSettings,
    experiment_session_id: Annotated[
        str, Header(alias="X-Experiment-Session-ID", min_length=1, max_length=36)
    ],
) -> StudentFeedbackItem:
    diagnosis = db.scalar(select(DiagnosisResult).where(DiagnosisResult.id == diagnosis_result_id))
    if diagnosis is None or diagnosis.device_id != device.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="diagnosis not found")
    try:
        record = submit_student_feedback(
            db,
            device,
            diagnosis,
            payload,
            experiment_session_id,
            getattr(request.app.state, "diagnosis_graph", None),
            settings,
        )
    except WorkflowScopeViolation as exc:
        db.rollback()
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except WorkflowConflict as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except Exception as exc:
        db.rollback()
        raise HTTPException(
            status_code=503,
            detail={
                "code": "DIAGNOSIS_FEEDBACK_RETRY_REQUIRED",
                "message": "retry the same request_id and payload; do not create a new submission",
            },
        ) from exc
    return StudentFeedbackItem(
        id=record.id,
        action=record.action,
        note=record.note,
        is_test_data=record.is_test_data,
        created_at=record.created_at,
    )


@router.get("/feedback-recovery", response_model=StudentFeedbackRecoveryResponse)
def get_feedback_recovery(
    device: AuthenticatedDevice,
    db: DatabaseSession,
    response: Response,
    experiment_session_id: Annotated[
        str, Header(alias="X-Experiment-Session-ID", min_length=1, max_length=36)
    ],
) -> StudentFeedbackRecoveryResponse:
    response.headers["Cache-Control"] = "no-store"
    try:
        return StudentFeedbackRecoveryResponse.model_validate(
            read_feedback_recovery(db, device, experiment_session_id)
        )
    except WorkflowScopeViolation as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
