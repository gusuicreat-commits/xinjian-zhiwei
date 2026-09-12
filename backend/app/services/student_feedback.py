"""Authorize before all writes and serialize retryable feedback across graph commits."""

import hashlib
from contextlib import contextmanager
from threading import RLock

from sqlalchemy import create_engine, select, text
from sqlalchemy.pool import NullPool

from app.models import DiagnosisFeedback, DiagnosisWorkflowRun
from app.services.diagnosis_workflow import (
    WorkflowConflict,
    WorkflowScopeViolation,
    assert_workflow_ownership,
    resolve_experiment_session,
    resume_workflow_with_feedback,
)
from app.services.student_dashboard import save_student_feedback

# SQLite is a single-process development/test backend. PostgreSQL uses a
# database session lock, held across the existing graph's business commits.
_LOCAL_LOCKS = [RLock() for _ in range(64)]


@contextmanager
def feedback_lock(db, diagnosis_id):
    key = int.from_bytes(hashlib.sha256(diagnosis_id.encode()).digest()[:8], "big", signed=True)
    bind = db.get_bind()
    if bind.dialect.name == "postgresql":
        engine = getattr(bind, "engine", bind)
        # Waiting advisory locks must not consume the business connection pool:
        # graph nodes release/reacquire business connections across commits.
        lock_engine = create_engine(engine.url, poolclass=NullPool)
        try:
            with lock_engine.connect().execution_options(
                isolation_level="AUTOCOMMIT"
            ) as connection:
                connection.execute(text("SELECT pg_advisory_lock(:key)"), {"key": key})
                try:
                    yield
                finally:
                    connection.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": key})
        finally:
            lock_engine.dispose()
    else:
        with _LOCAL_LOCKS[key % len(_LOCAL_LOCKS)]:
            yield


def submit_student_feedback(db, device, diagnosis, payload, session_id, graph, settings):
    diagnosis_id = diagnosis.id
    # The route has only authenticated/read so far. Release its read connection
    # while waiting; all ownership is revalidated under the serialization lock.
    db.rollback()
    with feedback_lock(db, diagnosis_id):
        # Re-read after serialization: a previous worker may have committed.
        db.expire_all()
        session = resolve_experiment_session(db, device, session_id, require_active=False)
        workflow = db.scalar(
            select(DiagnosisWorkflowRun)
            .where(DiagnosisWorkflowRun.diagnosis_result_id == diagnosis.id)
            .order_by(DiagnosisWorkflowRun.created_at.desc())
            .limit(1)
        )
        if workflow is not None:
            assert_workflow_ownership(
                db,
                workflow,
                expected_device_id=device.id,
                expected_student_user_id=session.student_user_id,
                expected_experiment_session_id=session.id,
            )
        else:
            # Only server-recorded creation scope is acceptable for legacy
            # deterministic runs. Never infer old ownership from today's binding.
            scope = (diagnosis.context_snapshot or {}).get("feedback_scope") or {}
            if scope != {
                "experiment_session_id": session.id,
                "student_user_id": session.student_user_id,
                "device_id": device.id,
            }:
                raise WorkflowScopeViolation("diagnosis has no matching recorded feedback scope")
        record = db.scalar(
            select(DiagnosisFeedback).where(
                DiagnosisFeedback.diagnosis_result_id == diagnosis.id,
                DiagnosisFeedback.request_id == str(payload.request_id),
            )
        )
        if record is not None:
            if (record.action, record.note, record.experiment_session_id) != (
                payload.action,
                payload.note,
                session.id,
            ):
                raise WorkflowConflict("feedback request_id was already used with another payload")
            if record.processing_status == "applied":
                return record
        else:
            if session.status != "active":
                raise WorkflowConflict("experiment session is not active")
            pending = db.scalar(
                select(DiagnosisFeedback.id)
                .where(
                    DiagnosisFeedback.diagnosis_result_id == diagnosis.id,
                    DiagnosisFeedback.request_id.is_not(None),
                    DiagnosisFeedback.processing_status == "pending",
                )
                .limit(1)
            )
            if pending is not None:
                raise WorkflowConflict(
                    "retry the pending feedback request before starting a new one"
                )
            if workflow is not None and workflow.status == "waiting_feedback" and graph is None:
                raise RuntimeError("workflow unavailable; feedback was not written")
            needs_resume = workflow is not None and workflow.status == "waiting_feedback"
            record = save_student_feedback(
                db,
                device,
                diagnosis,
                payload,
                experiment_session_id=session.id,
                processing_status="pending" if needs_resume else "applied",
            )
        if workflow is not None and record.processing_status == "pending":
            # Existing terminal workflows may accept feedback without restarting.
            # A pending interrupted submission must first reconcile its checkpoint.
            if graph is None:
                raise RuntimeError("workflow unavailable; retry the same request_id")
            resume_workflow_with_feedback(
                db,
                graph,
                workflow,
                record,
                device,
                settings,
                reconcile_only=session.status != "active",
            )
        else:
            record.processing_status = "applied"
            db.commit()
        db.refresh(record)
        return record
