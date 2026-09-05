from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from langgraph.types import Command
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.context_sanitizer import sanitize_text
from app.ai.diagnosis_graph import DiagnosisGraphContext, DiagnosisNodeExecutionError
from app.core.config import Settings
from app.diagnosis.workflow_schemas import (
    DiagnosisState,
    DiagnosisWorkflowResponse,
    DiagnosisWorkflowReviewRequest,
    DiagnosisWorkflowReviewResponse,
    DiagnosisWorkflowStartRequest,
)
from app.experiments.loader import load_experiment_definition
from app.models.base import new_uuid
from app.models.classroom import (
    ExperimentAssignment,
    ExperimentSession,
    TeachingAssignment,
    User,
)
from app.models.device import Device
from app.models.diagnosis_feedback import DiagnosisFeedback
from app.models.diagnosis_workflow import DiagnosisWorkflowRun
from app.services.experiment_packages import load_experiment_package_runtime


class WorkflowConflict(ValueError):
    pass


class WorkflowScopeViolation(PermissionError):
    pass


_TERMINAL_STATUSES = {"completed", "rejected"}


def _append_failed_node(workflow: DiagnosisWorkflowRun, exc: Exception) -> None:
    if not isinstance(exc, DiagnosisNodeExecutionError):
        return
    # Keep a bounded "latest failure per node" projection. This is a summary,
    # not an append-only attempt log, and therefore cannot inflate metrics when
    # the same checkpoint is retried repeatedly.
    retained = [
        item
        for item in (workflow.node_metrics or [])
        if not (
            isinstance(item, dict)
            and item.get("status") == "failed"
            and item.get("node") == exc.node
        )
    ]
    workflow.node_metrics = [
        *retained,
        {
            "node": exc.node,
            "duration_ms": exc.duration_ms,
            "status": "failed",
        },
    ]
    workflow.error_messages = list(
        dict.fromkeys([*(workflow.error_messages or []), exc.error_type])
    )


def _restore_checkpoint_observability(
    db: Session, workflow: DiagnosisWorkflowRun, graph: Any
) -> None:
    """Recover the last successful trace without copying full checkpoint state."""

    try:
        assert_workflow_ownership(db, workflow)
        checkpoint = graph.get_state(_config(workflow))
        values = checkpoint.values if checkpoint is not None else {}
    except Exception:
        return
    if not isinstance(values, dict):
        return
    trace = list(values.get("node_trace") or [])
    metrics = list(values.get("node_metrics") or [])
    if trace:
        workflow.node_trace = trace
        workflow.current_node = trace[-1]
    if metrics:
        failed = [
            item
            for item in (workflow.node_metrics or [])
            if isinstance(item, dict) and item.get("status") == "failed"
        ]
        succeeded_nodes = {
            item.get("node")
            for item in metrics
            if isinstance(item, dict) and item.get("status") == "succeeded"
        }
        workflow.node_metrics = [
            item for item in failed if item.get("node") not in succeeded_nodes
        ] + metrics


def thread_id(workflow_id: str) -> str:
    return f"diagnosis:{workflow_id}"


def _config(workflow: DiagnosisWorkflowRun) -> dict[str, Any]:
    expected = thread_id(workflow.id)
    if workflow.graph_thread_id != expected:
        raise WorkflowScopeViolation("workflow thread_id does not match diagnosis_id")
    return {"configurable": {"thread_id": expected}}


def resolve_experiment_session(
    db: Session,
    device: Device,
    experiment_session_id: str,
    *,
    require_active: bool = True,
) -> ExperimentSession:
    """Resolve a server-owned student/session/device tuple without trusting client IDs."""

    session = db.get(ExperimentSession, experiment_session_id)
    if session is None or session.device_id != device.id:
        raise WorkflowScopeViolation("experiment session is outside the authenticated device scope")
    if require_active and session.status != "active":
        raise WorkflowConflict("experiment session is not active")
    assignment = db.get(ExperimentAssignment, session.experiment_assignment_id)
    student = db.get(User, session.student_user_id)
    if assignment is None or student is None or not student.is_active:
        raise WorkflowScopeViolation("experiment session ownership is no longer valid")
    return session


def find_active_experiment_session(db: Session, device: Device) -> ExperimentSession | None:
    candidates = list(
        db.scalars(
            select(ExperimentSession)
            .where(
                ExperimentSession.device_id == device.id,
                ExperimentSession.status == "active",
            )
            .order_by(ExperimentSession.started_at.desc(), ExperimentSession.id.desc())
        )
    )
    valid: list[ExperimentSession] = []
    for item in candidates:
        try:
            valid.append(resolve_experiment_session(db, device, item.id))
        except (WorkflowConflict, WorkflowScopeViolation):
            continue
    if len(valid) > 1:
        raise WorkflowConflict("multiple active experiment sessions exist for this device")
    return valid[0] if valid else None


def assert_workflow_ownership(
    db: Session,
    workflow: DiagnosisWorkflowRun,
    *,
    expected_device_id: str | None = None,
    expected_student_user_id: str | None = None,
    expected_experiment_session_id: str | None = None,
) -> ExperimentSession:
    """Validate the immutable scope before any checkpoint read or resume."""

    _config(workflow)
    session = db.get(ExperimentSession, workflow.experiment_session_id)
    if session is None or (
        session.id != workflow.experiment_session_id
        or session.student_user_id != workflow.student_user_id
        or session.device_id != workflow.device_id
    ):
        raise WorkflowScopeViolation("diagnosis ownership does not match experiment session")
    if expected_device_id is not None and workflow.device_id != expected_device_id:
        raise WorkflowScopeViolation("diagnosis belongs to another device")
    if (
        expected_student_user_id is not None
        and workflow.student_user_id != expected_student_user_id
    ):
        raise WorkflowScopeViolation("diagnosis belongs to another student")
    if (
        expected_experiment_session_id is not None
        and workflow.experiment_session_id != expected_experiment_session_id
    ):
        raise WorkflowScopeViolation("diagnosis belongs to another experiment session")
    return session


def _interrupt_payload(result: dict[str, Any]) -> dict[str, Any] | None:
    interrupts = result.get("__interrupt__") or []
    if not interrupts:
        return None
    value = getattr(interrupts[0], "value", None)
    if not isinstance(value, dict):
        return {"value": value}
    # Both checkpoints and business APIs retain only stable structured-case
    # metadata and scores, never teacher notes or full case content.
    payload = dict(value)
    payload["retrieved_chunks"] = [
        _public_knowledge_reference(item)
        for item in value.get("retrieved_chunks", [])
        if isinstance(item, dict)
    ]
    return payload


def _public_knowledge_reference(item: dict[str, Any]) -> dict[str, Any]:
    metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
    locator = metadata.get("locator") if isinstance(metadata.get("locator"), dict) else {}
    return {
        "chunk_id": sanitize_text(item.get("chunk_id"), max_chars=100),
        "case_id": sanitize_text(item.get("case_id") or item.get("chunk_id"), max_chars=100),
        "source_id": sanitize_text(item.get("source_id"), max_chars=200),
        "title": sanitize_text(item.get("title"), max_chars=200),
        "score": float(item.get("score") or 0.0),
        "metadata": {
            "source_type": sanitize_text(metadata.get("source_type"), max_chars=100)
            if metadata.get("source_type")
            else None,
            "source_version": sanitize_text(metadata.get("source_version"), max_chars=100)
            if metadata.get("source_version")
            else None,
            "review_status": (
                "approved" if metadata.get("review_status") == "approved" else "unverified"
            ),
            "locator": {
                key: (sanitize_text(value, max_chars=200) if isinstance(value, str) else value)
                for key, value in locator.items()
                if key
                in {
                    "page",
                    "page_number",
                    "section",
                    "chapter",
                    "heading",
                    "chunk_index",
                }
                and isinstance(value, (str, int, float, bool))
            },
            "retrieval_scores": {
                key: float(value)
                for key, value in (metadata.get("retrieval_scores") or {}).items()
                if key == "structured_match" and isinstance(value, (int, float))
            },
            "is_test_data": bool(metadata.get("is_test_data")),
        },
    }


def _sync_business_record(
    db: Session,
    workflow: DiagnosisWorkflowRun,
    state: dict[str, Any],
    *,
    review_request: dict[str, Any] | None,
) -> DiagnosisWorkflowRun:
    trace = list(state.get("node_trace") or [])
    workflow.diagnosis_result_id = state.get("diagnosis_result_id") or workflow.diagnosis_result_id
    workflow.experiment_record_id = (
        state.get("experiment_record_id") or workflow.experiment_record_id
    )
    workflow.experiment_version_id = (
        state.get("experiment_version_id") or workflow.experiment_version_id
    )
    workflow.state_revision = int(workflow.state_revision or 0) + 1
    workflow.status = state.get("diagnosis_status") or state.get("status") or workflow.status
    workflow.current_node = trace[-1] if trace else workflow.current_node
    workflow.evidence_score = state.get("evidence_score")
    workflow.guidance_level = state.get("hint_level", state.get("guidance_level"))
    workflow.needs_rag = False
    workflow.needs_teacher = bool(state.get("need_teacher_help", state.get("needs_teacher", False)))
    workflow.rule_engine_version = state.get("rule_engine_version")
    workflow.fault_tree_version = state.get("fault_tree_version")
    workflow.model_id = state.get("model_id")
    workflow.node_trace = trace
    failed_metrics = [
        item
        for item in (workflow.node_metrics or [])
        if isinstance(item, dict) and item.get("status") == "failed"
    ]
    checkpoint_metrics = list(state.get("node_metrics") or [])
    succeeded_nodes = {
        item.get("node")
        for item in checkpoint_metrics
        if isinstance(item, dict) and item.get("status") == "succeeded"
    }
    workflow.node_metrics = [
        item for item in failed_metrics if item.get("node") not in succeeded_nodes
    ] + checkpoint_metrics
    chunks = list(state.get("knowledge_context") or state.get("retrieved_chunks") or [])
    workflow.retrieval_audit = {
        "mode": "structured_case_match",
        "query": state.get("retrieval_query"),
        "top_k": len(chunks),
        "matches": [
            {
                "chunk_id": item.get("chunk_id"),
                "source_id": item.get("source_id"),
                "score": item.get("score"),
            }
            for item in chunks
        ],
        "adopted_evidence_refs": [
            item.get("chunk_id")
            for item in chunks
            if item.get("chunk_id")
            and any(
                item.get("chunk_id") in (cause.get("knowledge_chunk_ids") or [])
                or item.get("chunk_id") in (cause.get("knowledge_case_ids") or [])
                for cause in (state.get("ai_result") or {}).get("possible_causes", [])
            )
        ],
    }
    workflow.error_messages = list(
        dict.fromkeys([*(workflow.error_messages or []), *(state.get("errors") or [])])
    )
    workflow.review_request = review_request
    if workflow.status == "waiting_teacher":
        workflow.current_node = "teacher_review"
    if review_request and review_request.get("kind") == "student_feedback":
        workflow.status = "waiting_feedback"
        workflow.current_node = "feedback_handler"
    if workflow.status in {"completed", "rejected", "failed"} and workflow.completed_at is None:
        workflow.completed_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(workflow)
    return workflow


def _reconcile_terminal_checkpoint(
    db: Session,
    graph: Any,
    workflow: DiagnosisWorkflowRun,
    *,
    context: DiagnosisGraphContext,
    resume: Command | None = None,
) -> dict[str, Any]:
    """Advance a checkpoint once after its terminal business commit succeeded.

    Business data and LangGraph's saver cannot share one portable transaction.
    Terminal nodes are replay-safe, so a single bounded replay closes the common
    "business committed, saver write failed" window. If the saver is still down,
    the caller receives 503 instead of a false success and can retry later.
    """

    db.expire_all()
    assert_workflow_ownership(db, workflow)
    result = graph.invoke(
        resume,
        config=_config(workflow),
        context=context,
    )
    return result


def start_workflow(
    db: Session,
    graph: Any,
    device: Device,
    settings: Settings,
    payload: DiagnosisWorkflowStartRequest,
    experiment_session: ExperimentSession | None = None,
) -> DiagnosisWorkflowRun:
    experiment_session = experiment_session or find_active_experiment_session(db, device)
    if experiment_session is None:
        raise WorkflowConflict("device has no active student experiment session")
    resolved_session = resolve_experiment_session(db, device, experiment_session.id)
    assignment = db.get(ExperimentAssignment, resolved_session.experiment_assignment_id)
    if assignment is None:
        raise WorkflowScopeViolation("experiment assignment no longer exists")
    package_version_id = payload.experiment_version_id or assignment.experiment_version_id
    if (
        payload.experiment_version_id
        and assignment.experiment_version_id
        and payload.experiment_version_id != assignment.experiment_version_id
    ):
        raise WorkflowScopeViolation("requested package version differs from the assignment")
    package_runtime = None
    if package_version_id:
        package_runtime = load_experiment_package_runtime(db, package_version_id)
        if (
            payload.experiment_id
            and payload.experiment_id != package_runtime.definition.experiment.id
        ):
            raise WorkflowScopeViolation("requested experiment differs from the package version")
        if (
            payload.experiment_version
            and payload.experiment_version != package_runtime.definition.experiment.version
        ):
            raise WorkflowScopeViolation("requested experiment version differs from the package")
    elif payload.experiment_id:
        # Compatibility path for the existing filesystem definitions.
        load_experiment_definition(payload.experiment_id, payload.experiment_version)
    workflow_id = new_uuid()
    workflow = DiagnosisWorkflowRun(
        id=workflow_id,
        device_id=device.id,
        student_user_id=resolved_session.student_user_id,
        experiment_session_id=resolved_session.id,
        graph_thread_id=thread_id(workflow_id),
        graph_version=settings.diagnosis_graph_version,
        status="created",
        current_node=None,
        experiment_record_id=(package_runtime.experiment.id if package_runtime else None),
        experiment_version_id=(package_runtime.version.id if package_runtime else None),
        question=payload.question,
        embedding_version=None,
        node_trace=[],
        error_messages=[],
        is_test_data=device.device_type in {"test-fixture", "generic-test-fixture"},
    )
    db.add(workflow)
    db.commit()
    db.refresh(workflow)
    initial_state: DiagnosisState = {
        "device_status": {},
        "experiment_type": (
            package_runtime.definition.experiment.id if package_runtime else payload.experiment_id
        ),
        "logs": [],
        "sensor_data": [],
        "sensor_values": [],
        "experiment_context": {},
        "error_type": None,
        "evidence": [],
        "possible_causes": [],
        "knowledge_context": [],
        "hint_level": 1,
        "student_feedback": None,
        "historical_failures": 0,
        "attempt_count": 0,
        "need_teacher_help": False,
        "diagnosis_status": "collecting",
        "failure_count": 0,
        "anomaly_duration_seconds": 0,
        "reasoned_causes": [],
        "reasoning_status": "unknown",
        "reasoning_summary": "尚未执行智能推理。",
        "reasoning_mode": "deterministic_fallback",
        "missing_evidence": [],
        "next_verification_action": None,
        "evidence_conflict": False,
        "evidence_registry": [],
        "allowed_verification_actions": [],
        "knowledge_validation": {},
        "diagnosis_id": workflow.id,
        "student_user_id": workflow.student_user_id,
        "experiment_session_id": workflow.experiment_session_id,
        "device_id": device.device_key,
        "experiment_template": (
            payload.experiment_template.model_dump(mode="json")
            if payload.experiment_template
            else None
        ),
        "experiment_id": (
            package_runtime.definition.experiment.id if package_runtime else payload.experiment_id
        ),
        "experiment_version": (
            package_runtime.definition.experiment.version
            if package_runtime
            else payload.experiment_version
        ),
        "experiment_record_id": (package_runtime.experiment.id if package_runtime else None),
        "experiment_version_id": (package_runtime.version.id if package_runtime else None),
        "experiment_package_hash": (
            package_runtime.version.package_hash if package_runtime else None
        ),
        # A workflow question is untrusted free text.  Keep only the redacted form
        # in checkpoint state; the original business input remains in the access-
        # controlled workflow row when it is needed for audit/support.
        "question": sanitize_text(payload.question, max_chars=2000) if payload.question else None,
        "lookback_seconds": payload.lookback_seconds,
        "evaluated_at": datetime.now(timezone.utc).isoformat(),
        "status": "collecting",
        "errors": [],
        "node_trace": [],
        "node_metrics": [],
    }
    try:
        result = graph.invoke(
            initial_state,
            config=_config(workflow),
            context=DiagnosisGraphContext(db=db, device=device, settings=settings),
        )
    except Exception as exc:
        db.rollback()
        workflow = db.get(DiagnosisWorkflowRun, workflow.id)
        if workflow is None:
            raise
        # The business terminal node commits atomically before the saver stores
        # its following checkpoint.  If only that infrastructure write failed,
        # preserve the already committed business truth; the replay-safe terminal
        # node can be resumed later without duplicating formal records.
        if workflow.status in _TERMINAL_STATUSES:
            result = _reconcile_terminal_checkpoint(
                db,
                graph,
                workflow,
                context=DiagnosisGraphContext(db=db, device=device, settings=settings),
            )
            return _sync_business_record(
                db,
                workflow,
                result,
                review_request=_interrupt_payload(result),
            )
        _restore_checkpoint_observability(db, workflow, graph)
        workflow.status = "failed"
        workflow.current_node = (
            exc.node if isinstance(exc, DiagnosisNodeExecutionError) else "workflow_error"
        )
        _append_failed_node(workflow, exc)
        if not workflow.error_messages:
            workflow.error_messages = [type(exc).__name__]
        workflow.completed_at = datetime.now(timezone.utc)
        db.commit()
        raise
    return _sync_business_record(
        db,
        workflow,
        result,
        review_request=_interrupt_payload(result),
    )


def review_workflow(
    db: Session,
    graph: Any,
    workflow: DiagnosisWorkflowRun,
    reviewer: User,
    settings: Settings,
    payload: DiagnosisWorkflowReviewRequest,
) -> DiagnosisWorkflowRun:
    # Serialize reviews for the same workflow in PostgreSQL and refresh any ORM
    # instance that the route loaded before waiting on the lock.  Without
    # populate_existing, a second request can retain the stale
    # ``waiting_teacher`` value in its identity map after the first request has
    # already completed the workflow.
    locked_workflow = db.scalar(
        select(DiagnosisWorkflowRun)
        .where(DiagnosisWorkflowRun.id == workflow.id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if locked_workflow is None:
        raise WorkflowConflict("workflow no longer exists")
    workflow = locked_workflow
    assert_workflow_ownership(db, workflow)
    if workflow.status != "waiting_teacher":
        raise WorkflowConflict("workflow is not waiting for teacher review")
    if workflow.diagnosis_result_id is None:
        raise WorkflowConflict("workflow has no diagnosis result")
    device = db.get(Device, workflow.device_id)
    if device is None:
        raise WorkflowConflict("workflow device no longer exists")
    edited_result = (
        payload.edited_result.model_dump(mode="json", exclude_none=True)
        if payload.edited_result
        else None
    )
    decision = {
        "action": payload.action,
        # The raw teacher review belongs to the business audit table, not the
        # LangGraph checkpoint.  Resume with a redacted copy so checkpoint dumps
        # cannot retain credentials accidentally pasted into review prose.
        "comment": sanitize_text(payload.comment, max_chars=4000) if payload.comment else None,
        "edited_result": (
            {
                key: (
                    sanitize_text(value, max_chars=1000)
                    if isinstance(value, str)
                    else [sanitize_text(item, max_chars=1000) for item in value]
                    if isinstance(value, list)
                    else value
                )
                for key, value in edited_result.items()
            }
            if edited_result
            else None
        ),
        "reviewer_user_id": reviewer.id,
    }
    try:
        result = graph.invoke(
            Command(resume=decision),
            config=_config(workflow),
            context=DiagnosisGraphContext(
                db=db,
                device=device,
                settings=settings,
                review_payload={
                    "action": payload.action,
                    "comment": payload.comment,
                    "edited_result": edited_result,
                    "reviewer_user_id": reviewer.id,
                },
            ),
        )
    except Exception as exc:
        # A failed resume must not create a durable review audit record.  The graph
        # checkpoint remains the source of truth for the still-pending interrupt,
        # so the exact same decision can be retried after the saver/node recovers.
        db.rollback()
        refreshed = db.get(DiagnosisWorkflowRun, workflow.id)
        if refreshed is not None:
            if refreshed.status in _TERMINAL_STATUSES:
                result = _reconcile_terminal_checkpoint(
                    db,
                    graph,
                    refreshed,
                    context=DiagnosisGraphContext(
                        db=db,
                        device=device,
                        settings=settings,
                        review_payload={
                            "action": payload.action,
                            "comment": payload.comment,
                            "edited_result": edited_result,
                            "reviewer_user_id": reviewer.id,
                        },
                    ),
                    resume=Command(resume=decision),
                )
                return _sync_business_record(
                    db,
                    refreshed,
                    result,
                    review_request=_interrupt_payload(result),
                )
            _restore_checkpoint_observability(db, refreshed, graph)
            _append_failed_node(refreshed, exc)
            if isinstance(exc, DiagnosisNodeExecutionError):
                db.commit()
        raise
    return _sync_business_record(
        db,
        workflow,
        result,
        review_request=_interrupt_payload(result),
    )


def resume_workflow_with_feedback(
    db: Session,
    graph: Any,
    workflow: DiagnosisWorkflowRun,
    feedback: DiagnosisFeedback,
    device: Device,
    settings: Settings,
) -> DiagnosisWorkflowRun:
    """Resume the same diagnosis state with student feedback as new evidence."""

    locked = db.scalar(
        select(DiagnosisWorkflowRun)
        .where(DiagnosisWorkflowRun.id == workflow.id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if locked is None:
        raise WorkflowConflict("workflow no longer exists")
    workflow = locked
    assert_workflow_ownership(db, workflow, expected_device_id=device.id)
    if workflow.status != "waiting_feedback":
        raise WorkflowConflict("workflow is not waiting for student feedback")
    if workflow.diagnosis_result_id != feedback.diagnosis_result_id:
        raise WorkflowScopeViolation("feedback belongs to another diagnosis")
    decision = {
        "id": feedback.id,
        "action": feedback.action,
        "note": sanitize_text(feedback.note, max_chars=1000) if feedback.note else None,
        "created_at": feedback.created_at.isoformat(),
    }
    try:
        result = graph.invoke(
            Command(resume=decision),
            config=_config(workflow),
            context=DiagnosisGraphContext(db=db, device=device, settings=settings),
        )
    except Exception:
        db.rollback()
        refreshed = db.get(DiagnosisWorkflowRun, workflow.id)
        if refreshed is not None and refreshed.status in _TERMINAL_STATUSES:
            result = _reconcile_terminal_checkpoint(
                db,
                graph,
                refreshed,
                context=DiagnosisGraphContext(db=db, device=device, settings=settings),
            )
            refreshed.resume_count = int(refreshed.resume_count or 0) + 1
            return _sync_business_record(
                db,
                refreshed,
                result,
                review_request=_interrupt_payload(result),
            )
        raise
    refreshed = db.get(DiagnosisWorkflowRun, workflow.id)
    if refreshed is None:
        raise WorkflowConflict("workflow no longer exists")
    refreshed.resume_count = int(refreshed.resume_count or 0) + 1
    return _sync_business_record(
        db,
        refreshed,
        result,
        review_request=_interrupt_payload(result),
    )


def teacher_can_review(db: Session, reviewer: User, workflow: DiagnosisWorkflowRun) -> bool:
    # Admin access is checked by the caller's permission dependency. Teachers must
    # additionally share a teaching assignment with the workflow device.
    return (
        db.scalar(
            select(ExperimentSession.id)
            .join(
                ExperimentAssignment,
                ExperimentAssignment.id == ExperimentSession.experiment_assignment_id,
            )
            .join(
                TeachingAssignment,
                TeachingAssignment.class_id == ExperimentAssignment.class_id,
            )
            .where(
                ExperimentSession.id == workflow.experiment_session_id,
                ExperimentSession.device_id == workflow.device_id,
                ExperimentSession.student_user_id == workflow.student_user_id,
                TeachingAssignment.user_id == reviewer.id,
            )
            .limit(1)
        )
        is not None
    )


def serialize_workflow(
    workflow: DiagnosisWorkflowRun,
    *,
    audience: str = "teacher",
) -> DiagnosisWorkflowResponse:
    is_student = audience == "student"
    public_review_request = workflow.review_request
    if is_student:
        public_review_request = (
            workflow.review_request
            if (workflow.review_request or {}).get("kind") == "student_feedback"
            else None
        )
    return DiagnosisWorkflowResponse(
        id=workflow.id,
        diagnosis_id=workflow.id,
        diagnosis_result_id=workflow.diagnosis_result_id,
        device_id=workflow.device.device_key,
        student_user_id=workflow.student_user_id,
        experiment_session_id=workflow.experiment_session_id,
        experiment_version_id=workflow.experiment_version_id,
        state_revision=workflow.state_revision,
        graph_thread_id=workflow.graph_thread_id,
        graph_version=workflow.graph_version,
        status=workflow.status,
        current_node=workflow.current_node,
        evidence_score=workflow.evidence_score,
        guidance_level=workflow.guidance_level,
        needs_rag=workflow.needs_rag,
        needs_teacher=workflow.needs_teacher,
        rule_engine_version=workflow.rule_engine_version,
        fault_tree_version=workflow.fault_tree_version,
        embedding_version=workflow.embedding_version,
        model_id=workflow.model_id,
        node_trace=workflow.node_trace,
        node_metrics=[] if is_student else workflow.node_metrics,
        retrieval_audit={} if is_student else workflow.retrieval_audit,
        resume_count=workflow.resume_count,
        final_result=workflow.final_result,
        error_messages=workflow.error_messages,
        review_request=public_review_request,
        reviews=[
            DiagnosisWorkflowReviewResponse(
                id=item.id,
                reviewer_user_id=("hidden" if is_student else item.reviewer_user_id),
                action=item.action,
                comment=None if is_student else item.comment,
                edited_result=None if is_student else item.edited_result,
                created_at=item.created_at,
            )
            for item in sorted(workflow.reviews, key=lambda item: (item.created_at, item.id))
        ],
        is_test_data=workflow.is_test_data,
        created_at=workflow.created_at,
        updated_at=workflow.updated_at,
        completed_at=workflow.completed_at,
    )
