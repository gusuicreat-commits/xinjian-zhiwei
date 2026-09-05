from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from sqlalchemy import exists, func, select
from sqlalchemy.orm import Session

from app.api.dependencies import get_authenticated_device, require_permission
from app.core.config import Settings, get_settings
from app.db.session import get_db
from app.diagnosis.workflow_schemas import (
    DiagnosisWorkflowMetricsResponse,
    DiagnosisWorkflowResponse,
    DiagnosisWorkflowReviewRequest,
    DiagnosisWorkflowStartRequest,
)
from app.experiment_packages.loader import ExperimentPackageLoadError
from app.experiments.loader import ExperimentDefinitionLoadError
from app.models.ai_call_record import AICallRecord
from app.models.classroom import ExperimentAssignment, ExperimentSession, TeachingAssignment, User
from app.models.device import Device
from app.models.diagnosis_feedback import DiagnosisFeedback
from app.models.diagnosis_workflow import DiagnosisWorkflowReview, DiagnosisWorkflowRun
from app.services.auth import user_access
from app.services.diagnosis_workflow import (
    WorkflowConflict,
    WorkflowScopeViolation,
    assert_workflow_ownership,
    resolve_experiment_session,
    review_workflow,
    serialize_workflow,
    start_workflow,
    teacher_can_review,
)

router = APIRouter(prefix="/diagnosis-workflows", tags=["diagnosis-workflows"])
DatabaseSession = Annotated[Session, Depends(get_db)]
AuthenticatedDevice = Annotated[Device, Depends(get_authenticated_device)]
WorkflowReviewer = Annotated[User, Depends(require_permission("intervention.manage"))]
AppSettings = Annotated[Settings, Depends(get_settings)]
ExperimentSessionHeader = Annotated[
    str, Header(alias="X-Experiment-Session-ID", min_length=1, max_length=36)
]


def _graph(request: Request):
    graph = getattr(request.app.state, "diagnosis_graph", None)
    if graph is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "DIAGNOSIS_GRAPH_UNAVAILABLE", "message": "workflow is disabled"},
        )
    return graph


def _reviewer_scoped_workflows(reviewer: User, db: Session):
    roles, _ = user_access(db, reviewer.id)
    query = select(DiagnosisWorkflowRun)
    if "admin" not in roles:
        query = (
            query.join(
                ExperimentSession,
                ExperimentSession.id == DiagnosisWorkflowRun.experiment_session_id,
            )
            .join(
                ExperimentAssignment,
                ExperimentAssignment.id == ExperimentSession.experiment_assignment_id,
            )
            .join(
                TeachingAssignment,
                TeachingAssignment.class_id == ExperimentAssignment.class_id,
            )
            .where(
                ExperimentSession.device_id == DiagnosisWorkflowRun.device_id,
                ExperimentSession.student_user_id == DiagnosisWorkflowRun.student_user_id,
                TeachingAssignment.user_id == reviewer.id,
            )
        )
    return query


@router.post(
    "/devices/{device_id}",
    response_model=DiagnosisWorkflowResponse,
    status_code=status.HTTP_201_CREATED,
)
def start_diagnosis_workflow(
    device_id: str,
    payload: DiagnosisWorkflowStartRequest,
    request: Request,
    device: AuthenticatedDevice,
    db: DatabaseSession,
    settings: AppSettings,
    experiment_session_id: ExperimentSessionHeader,
) -> DiagnosisWorkflowResponse:
    if device_id != device.device_key:
        raise HTTPException(status_code=403, detail="device id mismatch")
    try:
        experiment_session = resolve_experiment_session(db, device, experiment_session_id)
        workflow = start_workflow(
            db, _graph(request), device, settings, payload, experiment_session
        )
    except WorkflowScopeViolation as exc:
        raise HTTPException(
            status_code=403,
            detail={"code": "DIAGNOSIS_SCOPE_DENIED", "message": str(exc)},
        ) from exc
    except WorkflowConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except (ExperimentDefinitionLoadError, ExperimentPackageLoadError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail={
                "code": "DIAGNOSIS_WORKFLOW_FAILED",
                "message": "workflow failed; the legacy deterministic diagnosis remains available",
            },
        ) from exc
    return serialize_workflow(workflow, audience="student")


@router.get(
    "/devices/{device_id}/latest",
    response_model=DiagnosisWorkflowResponse | None,
)
def get_latest_device_workflow(
    device_id: str,
    device: AuthenticatedDevice,
    db: DatabaseSession,
    experiment_session_id: ExperimentSessionHeader,
) -> DiagnosisWorkflowResponse | None:
    if device_id != device.device_key:
        raise HTTPException(status_code=403, detail="device id mismatch")
    try:
        experiment_session = resolve_experiment_session(db, device, experiment_session_id)
    except (WorkflowConflict, WorkflowScopeViolation) as exc:
        raise HTTPException(status_code=404, detail="experiment session not found") from exc
    workflow = db.scalar(
        select(DiagnosisWorkflowRun)
        .where(
            DiagnosisWorkflowRun.device_id == device.id,
            DiagnosisWorkflowRun.student_user_id == experiment_session.student_user_id,
            DiagnosisWorkflowRun.experiment_session_id == experiment_session.id,
        )
        .order_by(DiagnosisWorkflowRun.created_at.desc(), DiagnosisWorkflowRun.id.desc())
        .limit(1)
    )
    return serialize_workflow(workflow, audience="student") if workflow is not None else None


@router.get("/review-queue/pending", response_model=list[DiagnosisWorkflowResponse])
def pending_review_queue(
    reviewer: WorkflowReviewer,
    db: DatabaseSession,
) -> list[DiagnosisWorkflowResponse]:
    query = (
        _reviewer_scoped_workflows(reviewer, db)
        .where(DiagnosisWorkflowRun.status == "waiting_teacher")
        .order_by(DiagnosisWorkflowRun.updated_at)
    )
    return [serialize_workflow(item) for item in db.scalars(query).unique()]


@router.get("/review-queue/recent", response_model=list[DiagnosisWorkflowResponse])
def recent_review_history(
    reviewer: WorkflowReviewer,
    db: DatabaseSession,
) -> list[DiagnosisWorkflowResponse]:
    query = (
        _reviewer_scoped_workflows(reviewer, db)
        .where(
            DiagnosisWorkflowRun.status.in_(("completed", "rejected")),
            exists().where(DiagnosisWorkflowReview.workflow_run_id == DiagnosisWorkflowRun.id),
        )
        .order_by(
            DiagnosisWorkflowRun.updated_at.desc(),
            DiagnosisWorkflowRun.id.desc(),
        )
        .limit(50)
    )
    return [serialize_workflow(item) for item in db.scalars(query).unique()]


@router.get("/metrics/summary", response_model=DiagnosisWorkflowMetricsResponse)
def diagnosis_workflow_metrics(
    reviewer: WorkflowReviewer,
    db: DatabaseSession,
) -> DiagnosisWorkflowMetricsResponse:
    workflows = list(db.scalars(_reviewer_scoped_workflows(reviewer, db)).unique())
    reviewed_workflows = [item for item in workflows if item.reviews]
    review_actions = {item.id: item.reviews[-1].action for item in reviewed_workflows}
    node_durations = [
        float(metric["duration_ms"])
        for workflow in workflows
        for metric in (getattr(workflow, "node_metrics", None) or [])
        if isinstance(metric, dict) and isinstance(metric.get("duration_ms"), (int, float))
    ]
    workflow_ids = [item.id for item in workflows]
    diagnosis_ids = [item.diagnosis_result_id for item in workflows if item.diagnosis_result_id]
    if workflow_ids:
        ai_metrics = db.execute(
            select(
                func.count(AICallRecord.id),
                func.coalesce(func.sum(AICallRecord.input_tokens), 0),
                func.coalesce(func.sum(AICallRecord.output_tokens), 0),
                func.coalesce(func.sum(AICallRecord.estimated_cost), 0.0),
            ).where(AICallRecord.workflow_run_id.in_(workflow_ids))
        ).one()
    else:
        ai_metrics = (0, 0, 0, 0.0)
    if diagnosis_ids:
        feedback_rows = db.execute(
            select(
                DiagnosisFeedback.diagnosis_result_id,
                DiagnosisFeedback.action,
            )
            .where(DiagnosisFeedback.diagnosis_result_id.in_(diagnosis_ids))
            .order_by(DiagnosisFeedback.created_at, DiagnosisFeedback.id)
        ).all()
        latest_feedback = {
            diagnosis_result_id: action for diagnosis_result_id, action in feedback_rows
        }
        feedback_count = len(latest_feedback)
        resolved_count = sum(action == "resolved" for action in latest_feedback.values())
    else:
        feedback_count, resolved_count = 0, 0
    reviewed_count = len(reviewed_workflows)
    return DiagnosisWorkflowMetricsResponse(
        total=len(workflows),
        in_progress=sum(
            item.status
            in {
                "created",
                "collecting",
                "deterministic_analysis",
                "retrieving",
                "ai_analysis",
                "waiting_feedback",
            }
            for item in workflows
        ),
        completed=sum(item.status == "completed" for item in workflows),
        waiting_teacher=sum(item.status == "waiting_teacher" for item in workflows),
        rejected=sum(item.status == "rejected" for item in workflows),
        failed=sum(item.status == "failed" for item in workflows),
        reviewed=reviewed_count,
        edit_rate=(
            sum(action == "edit" for action in review_actions.values()) / reviewed_count
            if reviewed_count
            else 0.0
        ),
        reject_rate=(
            sum(action == "reject" for action in review_actions.values()) / reviewed_count
            if reviewed_count
            else 0.0
        ),
        needs_rag_count=sum(item.needs_rag for item in workflows),
        resume_count=sum(int(getattr(item, "resume_count", 0) or 0) for item in workflows),
        average_node_duration_ms=(
            sum(node_durations) / len(node_durations) if node_durations else None
        ),
        ai_call_count=int(ai_metrics[0] or 0),
        ai_input_tokens=int(ai_metrics[1] or 0),
        ai_output_tokens=int(ai_metrics[2] or 0),
        ai_estimated_cost=float(ai_metrics[3] or 0.0),
        student_feedback_count=int(feedback_count or 0),
        student_resolved_count=int(resolved_count or 0),
        student_resolution_rate=(
            int(resolved_count or 0) / int(feedback_count) if feedback_count else None
        ),
    )


@router.get("/{workflow_id}", response_model=DiagnosisWorkflowResponse)
def get_device_workflow(
    workflow_id: str,
    device: AuthenticatedDevice,
    db: DatabaseSession,
    experiment_session_id: ExperimentSessionHeader,
) -> DiagnosisWorkflowResponse:
    workflow = db.get(DiagnosisWorkflowRun, workflow_id)
    if workflow is None or workflow.device_id != device.id:
        raise HTTPException(status_code=404, detail="diagnosis workflow not found")
    try:
        experiment_session = resolve_experiment_session(
            db, device, experiment_session_id, require_active=True
        )
        assert_workflow_ownership(
            db,
            workflow,
            expected_device_id=device.id,
            expected_student_user_id=experiment_session.student_user_id,
            expected_experiment_session_id=experiment_session.id,
        )
    except (WorkflowConflict, WorkflowScopeViolation) as exc:
        raise HTTPException(status_code=404, detail="diagnosis workflow not found") from exc
    return serialize_workflow(workflow, audience="student")


@router.post("/{workflow_id}/review", response_model=DiagnosisWorkflowResponse)
def review_diagnosis_workflow(
    workflow_id: str,
    payload: DiagnosisWorkflowReviewRequest,
    request: Request,
    reviewer: WorkflowReviewer,
    db: DatabaseSession,
    settings: AppSettings,
) -> DiagnosisWorkflowResponse:
    workflow = db.get(DiagnosisWorkflowRun, workflow_id)
    if workflow is None:
        raise HTTPException(status_code=404, detail="diagnosis workflow not found")
    try:
        assert_workflow_ownership(db, workflow)
    except WorkflowScopeViolation as exc:
        raise HTTPException(
            status_code=409,
            detail={"code": "DIAGNOSIS_SCOPE_INVALID", "message": str(exc)},
        ) from exc
    roles, _ = user_access(db, reviewer.id)
    if "admin" not in roles and not teacher_can_review(db, reviewer, workflow):
        raise HTTPException(
            status_code=403,
            detail={
                "code": "WORKFLOW_SCOPE_DENIED",
                "message": "The diagnosis workflow is outside the current user's scope",
            },
        )
    try:
        updated = review_workflow(
            db,
            _graph(request),
            workflow,
            reviewer,
            settings,
            payload,
        )
    except WorkflowConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail={
                "code": "DIAGNOSIS_WORKFLOW_RESUME_FAILED",
                "message": "workflow resume failed; review can be retried after recovery",
            },
        ) from exc
    return serialize_workflow(updated)
