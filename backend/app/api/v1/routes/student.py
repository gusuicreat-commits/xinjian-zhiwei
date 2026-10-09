from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_user, get_student_device, revalidate_student_access
from app.core.config import Settings, get_settings
from app.db.session import get_db
from app.experiment_packages.loader import ExperimentPackageLoadError
from app.models.classroom import DeviceBinding, ExperimentAssignment, ExperimentSession, User
from app.models.device import Device
from app.models.diagnosis_result import DiagnosisResult
from app.schemas.student import (
    ExperimentSessionEnd,
    ExperimentSessionStart,
    QueryAnswerCreate,
    QueryAnswerReceiptResponse,
    QueryTaskResponse,
    StudentDashboardResponse,
    StudentFeedbackCreate,
    StudentFeedbackItem,
    StudentFeedbackRecoveryResponse,
    StudentSessionResponse,
)
from app.services.data_scope import assert_student_assignment_access, assert_student_session_access
from app.services.diagnosis_workflow import (
    WorkflowConflict,
    WorkflowScopeViolation,
)
from app.services.experiment_sessions import end_session, session_summary, start_session
from app.services.query_tasks import (
    QueryConflict,
    QueryUnavailable,
    read_query,
    start_query,
    submit_answer,
)
from app.services.student_authorization import StudentActorContext
from app.services.student_dashboard import build_student_dashboard
from app.services.student_feedback import read_feedback_recovery, submit_student_feedback

router = APIRouter(prefix="/student", tags=["student"])
AuthenticatedDevice = Annotated[Device, Depends(get_student_device)]
DatabaseSession = Annotated[Session, Depends(get_db)]
AppSettings = Annotated[Settings, Depends(get_settings)]


@router.get("/assignments")
def student_assignments(user: Annotated[User, Depends(get_current_user)], db: DatabaseSession):
    result = []
    for assignment in db.scalars(
        select(ExperimentAssignment)
        .where(ExperimentAssignment.status == "published")
        .order_by(ExperimentAssignment.id)
    ):
        try:
            assert_student_assignment_access(db, user, assignment)
        except (WorkflowConflict, WorkflowScopeViolation):
            continue
        devices = list(
            db.scalars(
                select(Device)
                .where(
                    Device.is_active.is_(True),
                    select(DeviceBinding.id)
                    .where(
                        DeviceBinding.device_id == Device.id,
                        DeviceBinding.student_user_id == user.id,
                        DeviceBinding.class_id == assignment.class_id,
                        DeviceBinding.is_active.is_(True),
                        (DeviceBinding.experiment_assignment_id == assignment.id)
                        | DeviceBinding.experiment_assignment_id.is_(None),
                    )
                    .exists(),
                )
                .order_by(Device.device_key)
            )
        )
        result.append(
            {
                "id": assignment.id,
                "title": assignment.title,
                "is_test_data": assignment.is_test_data,
                "devices": [{"id": d.device_key, "name": d.display_name} for d in devices],
            }
        )
    return result


@router.post("/experiment-sessions", status_code=201)
def begin_experiment(
    payload: ExperimentSessionStart,
    user: Annotated[User, Depends(get_current_user)],
    db: DatabaseSession,
) -> dict:
    try:
        return start_session(
            db,
            user,
            request_id=payload.request_id,
            device_key=payload.device_id,
            assignment_id=str(payload.experiment_assignment_id),
        )
    except WorkflowScopeViolation as exc:
        db.rollback()
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except (WorkflowConflict, ExperimentPackageLoadError) as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/experiment-sessions/{session_id}/end")
def finish_experiment(
    session_id: str,
    payload: ExperimentSessionEnd,
    user: Annotated[User, Depends(get_current_user)],
    db: DatabaseSession,
) -> dict:
    try:
        return end_session(
            db,
            user,
            session_id=session_id,
            request_id=payload.request_id,
            expected_version=payload.expected_version,
            reason=payload.reason,
        )
    except WorkflowScopeViolation as exc:
        db.rollback()
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except WorkflowConflict as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/experiment-sessions")
def list_student_sessions(
    user: Annotated[User, Depends(get_current_user)],
    db: DatabaseSession,
) -> list[dict]:
    result = []
    for session in db.scalars(
        select(ExperimentSession)
        .where(
            ExperimentSession.student_user_id == user.id,
            ExperimentSession.status == "active",
            ExperimentSession.ended_at.is_(None),
        )
        .order_by(ExperimentSession.started_at.desc(), ExperimentSession.id)
    ):
        try:
            assert_student_session_access(db, user, session)
        except (WorkflowConflict, WorkflowScopeViolation):
            continue
        device = db.get(Device, session.device_id)
        if device is None or not device.is_active:
            continue
        result.append(session_summary(db, session))
    return result


@router.post("/session", response_model=StudentSessionResponse)
def create_student_session(
    device: AuthenticatedDevice, db: DatabaseSession, request: Request
) -> StudentSessionResponse:
    try:
        experiment_session = request.state.student_experiment_session
    except WorkflowConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return StudentSessionResponse(
        device_id=device.device_key,
        display_name=device.display_name,
        auth_mode=request.state.student_auth_mode,
        student_user_id=(experiment_session.student_user_id if experiment_session else None),
        experiment_session_id=(experiment_session.id if experiment_session else None),
        experiment_assignment_id=(
            experiment_session.experiment_assignment_id if experiment_session else None
        ),
        notice=(
            (
                "学生账号和实验资格已验证。"
                if request.state.student_auth_mode == "student_account"
                else "测试演示：设备凭据仅可访问明确标记的测试会话。"
            )
            if experiment_session
            else "当前设备没有唯一有效的学生实验会话；LangGraph 诊断已关闭。"
        ),
    )


@router.get("/dashboard", response_model=StudentDashboardResponse)
def get_student_dashboard(
    device: AuthenticatedDevice,
    db: DatabaseSession,
    request: Request,
    experiment_session_id: Annotated[str | None, Header(alias="X-Experiment-Session-ID")] = None,
) -> StudentDashboardResponse:
    try:
        selected = request.state.student_experiment_session
        return build_student_dashboard(db, device, selected.id if selected else None)
    except WorkflowScopeViolation as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except WorkflowConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


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
    from app.api.dependencies import student_actor_context
    from app.services.auth import AuthorizationDenied

    identity = student_actor_context(
        request, db, device, db.get(ExperimentSession, experiment_session_id)
    )
    try:
        record = submit_student_feedback(
            db,
            device,
            diagnosis,
            payload,
            experiment_session_id,
            getattr(request.app.state, "diagnosis_graph", None),
            settings,
            authorize=lambda: revalidate_student_access(request, db),
            student_actor=identity,
        )
    except AuthorizationDenied:
        db.rollback()
        raise
    except HTTPException:
        db.rollback()
        raise
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
        episode_id=record.episode_id,
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


@router.get("/experiment-session-commands/{request_id}")
def experiment_session_command_receipt(
    request_id: str,
    user: Annotated[User, Depends(get_current_user)],
    db: DatabaseSession,
):
    """Positive recovery only: absence cannot establish a previous request failed."""
    from app.models.classroom import ExperimentSessionCommand
    from app.services.auth import authorize_actor, current_actor
    from app.services.experiment_sessions import assert_session_management

    command = db.scalar(
        select(ExperimentSessionCommand).where(
            ExperimentSessionCommand.actor_user_id == user.id,
            ExperimentSessionCommand.request_id == request_id,
        )
    )
    if command is None:
        raise HTTPException(status_code=404, detail="command receipt not available")
    session = db.get(ExperimentSession, command.session_id)
    try:
        if session and session.student_user_id == user.id:
            authorize_actor(db, current_actor(user), "assignment.read")
            assert_student_session_access(db, user, session, require_active=False)
        else:
            authorize_actor(db, current_actor(user), "assignment.manage")
            assert_session_management(db, user, session)
    except WorkflowScopeViolation as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    return {"status": "applied", "request_id": command.request_id, "result": command.result_json}


# Query commands use the same runtime identity and authorization service as the
# other student routes. Resolve ended sessions here so original answer receipts
# can be confirmed; the service forbids every new operation in that scope.
def _query_actor(request: Request, db: DatabaseSession):
    from app.api.dependencies import get_authenticated_device
    from app.services.auth import AuthorizationDenied, current_actor
    from app.services.student_authorization import StudentActorContext

    authorization = request.headers.get("Authorization")
    if authorization:
        user = get_current_user(db, authorization)
        actor = current_actor(user)
        device = db.scalar(
            select(Device).where(Device.device_key == request.headers.get("X-Device-ID"))
        )
        if device is None:
            raise AuthorizationDenied(403)
        return StudentActorContext(
            device.id, request.headers.get("X-Experiment-Session-ID"), account=actor
        )
    if not request.headers.get("X-Device-Token"):
        raise AuthorizationDenied(401)
    device = get_authenticated_device(
        request, db, request.headers.get("X-Device-Token"), request.headers.get("X-Device-ID")
    )
    return StudentActorContext(
        device.id,
        request.headers.get("X-Experiment-Session-ID"),
        demo_device_hash=device.token_hash,
    )


QueryActor = Annotated[StudentActorContext, Depends(_query_actor)]


def _query_command(db, operation, *args, **kwargs):
    try:
        return operation(db, *args, **kwargs)
    except QueryUnavailable as exc:
        raise HTTPException(status_code=503, detail="query_temporarily_unavailable") from exc
    except QueryConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        # Invalid scenarios/enum pairs never expose database or source payloads.
        db.rollback()
        raise HTTPException(status_code=422, detail="invalid_query_request") from exc


@router.post("/diagnoses/{diagnosis_result_id}/queries", response_model=QueryTaskResponse)
def begin_student_query(
    diagnosis_result_id: str, identity: QueryActor, db: DatabaseSession, response: Response
):
    response.headers["Cache-Control"] = "no-store"
    return _query_command(db, start_query, identity, diagnosis_result_id)


@router.get("/queries/{task_id}", response_model=QueryTaskResponse)
def read_student_query(task_id: str, identity: QueryActor, db: DatabaseSession, response: Response):
    response.headers["Cache-Control"] = "no-store"
    return _query_command(db, read_query, identity, task_id)


@router.post("/queries/{task_id}/answers", response_model=QueryAnswerReceiptResponse)
def submit_student_query_answer(
    task_id: str,
    payload: QueryAnswerCreate,
    identity: QueryActor,
    db: DatabaseSession,
    response: Response,
):
    response.headers["Cache-Control"] = "no-store"
    return _query_command(db, submit_answer, identity, task_id, **payload.model_dump(mode="json"))
