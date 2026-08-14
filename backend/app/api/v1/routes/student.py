from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.dependencies import get_authenticated_device
from app.db.session import get_db
from app.models.device import Device
from app.models.diagnosis_result import DiagnosisResult
from app.schemas.student import (
    StudentDashboardResponse,
    StudentFeedbackCreate,
    StudentFeedbackItem,
    StudentSessionResponse,
)
from app.services.diagnosis_workflow import (
    WorkflowConflict,
    find_active_experiment_session,
)
from app.services.student_dashboard import build_student_dashboard, save_student_feedback

router = APIRouter(prefix="/student", tags=["student"])
AuthenticatedDevice = Annotated[Device, Depends(get_authenticated_device)]
DatabaseSession = Annotated[Session, Depends(get_db)]


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
    device: AuthenticatedDevice,
    db: DatabaseSession,
) -> StudentFeedbackItem:
    diagnosis = db.scalar(select(DiagnosisResult).where(DiagnosisResult.id == diagnosis_result_id))
    if diagnosis is None or diagnosis.device_id != device.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="diagnosis not found")
    record = save_student_feedback(db, device, diagnosis, payload)
    return StudentFeedbackItem(
        id=record.id,
        action=record.action,
        note=record.note,
        is_test_data=record.is_test_data,
        created_at=record.created_at,
    )
