"""Server-owned session scope shared by reads, ingestion and case authorization."""

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.classroom import ExperimentAssignment, ExperimentSession, User
from app.models.diagnosis_result import DiagnosisResult
from app.models.diagnosis_workflow import DiagnosisWorkflowRun


class ScopeConflict(ValueError):
    pass


class ScopeViolation(PermissionError):
    pass


def resolve_experiment_session(db, device, session_id, *, require_active=True):
    session = db.get(ExperimentSession, session_id)
    if session is None or session.device_id != device.id:
        raise ScopeViolation("experiment session is outside the authenticated device scope")
    if require_active and (session.status != "active" or session.ended_at is not None):
        raise ScopeConflict("experiment session is not active")
    assignment = db.get(ExperimentAssignment, session.experiment_assignment_id)
    student = db.get(User, session.student_user_id)
    if assignment is None or student is None or not student.is_active:
        raise ScopeViolation("experiment session ownership is no longer valid")
    return session


def find_active_experiment_session(db, device):
    candidates = db.scalars(
        select(ExperimentSession).where(
            ExperimentSession.device_id == device.id,
            ExperimentSession.status == "active",
            ExperimentSession.ended_at.is_(None),
        )
    )
    valid = []
    for item in candidates:
        try:
            valid.append(resolve_experiment_session(db, device, item.id))
        except (ScopeConflict, ScopeViolation):
            continue
    if len(valid) > 1:
        raise ScopeConflict("multiple active experiment sessions exist for this device")
    return valid[0] if valid else None


def diagnosis_session(db: Session, diagnosis: DiagnosisResult):
    """Return only a consistent persisted owner; never infer from current bindings."""
    workflow = db.scalar(
        select(DiagnosisWorkflowRun).where(DiagnosisWorkflowRun.diagnosis_result_id == diagnosis.id)
    )
    recorded = (diagnosis.context_snapshot or {}).get("feedback_scope")
    scopes = []
    if workflow is not None:
        scopes.append(
            (workflow.experiment_session_id, workflow.student_user_id, workflow.device_id)
        )
    if recorded:
        if not isinstance(recorded, dict):
            return None
        scopes.append(
            tuple(
                recorded.get(key)
                for key in ("experiment_session_id", "student_user_id", "device_id")
            )
        )
    if not scopes or any(scope != scopes[0] for scope in scopes):
        return None
    session_id, student_id, device_id = scopes[0]
    session = db.get(ExperimentSession, session_id) if session_id else None
    if (
        session is None
        or session.student_user_id != student_id
        or session.device_id != device_id
        or device_id != diagnosis.device_id
        or db.get(ExperimentAssignment, session.experiment_assignment_id) is None
    ):
        return None
    return session


def _utc(value: datetime):
    return (
        value.replace(tzinfo=timezone.utc)
        if value.tzinfo is None
        else value.astimezone(timezone.utc)
    )


def ingestion_session_id(db, device, observed_at, explicit_session_id=None):
    """Attach at receipt only; delayed/ambiguous records remain unowned."""
    if explicit_session_id is not None:
        return resolve_experiment_session(db, device, explicit_session_id).id
    try:
        session = find_active_experiment_session(db, device)
    except ScopeConflict:
        return None
    if session is None or _utc(observed_at) < _utc(session.started_at):
        return None
    return session.id
