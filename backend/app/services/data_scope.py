"""Server-owned session scope shared by reads, ingestion and case authorization."""

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.classroom import (
    Classroom,
    Enrollment,
    ExperimentAssignment,
    ExperimentSession,
    TeachingAssignment,
    User,
)
from app.models.diagnosis_result import DiagnosisResult
from app.models.diagnosis_workflow import DiagnosisWorkflowRun


class ScopeConflict(ValueError):
    pass


class ScopeViolation(PermissionError):
    pass


def assert_student_session_access(db, student, session, *, require_active=True):
    """BR-AUTH: authenticate the person independently from the recorded device owner."""
    if session.student_user_id != student.id:
        raise ScopeViolation("experiment session belongs to another student")
    assignment = db.get(ExperimentAssignment, session.experiment_assignment_id)
    assert_student_assignment_access(db, student, assignment, require_open=require_active)
    if require_active and (session.status != "active" or session.ended_at is not None):
        raise ScopeConflict("experiment session is not open")
    return session


def assert_student_assignment_access(db, student, assignment, *, require_open=True):
    from app.services.auth import user_access

    roles, permissions = user_access(db, student.id)
    classroom = db.get(Classroom, assignment.class_id) if assignment else None
    if (
        not student.is_active
        or "student" not in roles
        or "assignment.read" not in permissions
        or classroom is None
        or not classroom.is_active
        or db.scalar(
            select(Enrollment.id).where(
                Enrollment.class_id == classroom.id,
                Enrollment.user_id == student.id,
                Enrollment.status == "active",
            )
        )
        is None
    ):
        raise ScopeViolation("student does not have current access to the recorded session")
    if require_open:
        now = datetime.now(timezone.utc)
        if (
            assignment.status != "published"
            or (assignment.starts_at and _utc(assignment.starts_at) > now)
            or (assignment.due_at and _utc(assignment.due_at) <= now)
        ):
            raise ScopeConflict("experiment session or assignment is not open")
    return assignment


def teacher_has_class_access(db, actor, class_id):
    from app.services.auth import user_access

    if actor is None or not actor.is_active or class_id is None:
        return False
    roles, permissions = user_access(db, actor.id)
    if "admin" in roles:
        return True
    return (
        "intervention.manage" in permissions
        and "teacher" in roles
        and db.scalar(
            select(TeachingAssignment.id).where(
                TeachingAssignment.class_id == class_id,
                TeachingAssignment.user_id == actor.id,
            )
        )
        is not None
    )


def is_demo_device(device):
    return bool(device.metadata_json.get("is_test_data")) or device.device_type in {
        "test-fixture",
        "generic-test-fixture",
        "synthetic-test-device",
    }


def is_demo_session(db, session):
    assignment = db.get(ExperimentAssignment, session.experiment_assignment_id)
    student = db.get(User, session.student_user_id)
    classroom = db.get(Classroom, assignment.class_id) if assignment else None
    return bool(
        session.is_test_data
        and student
        and student.is_test_data
        and assignment
        and assignment.is_test_data
        and classroom
        and classroom.is_test_data
    )


def resolve_experiment_session(db, device, session_id, *, require_active=True):
    session = db.get(ExperimentSession, session_id)
    if session is None or session.device_id != device.id:
        raise ScopeViolation("experiment session is outside the authenticated device scope")
    if require_active and (session.status != "active" or session.ended_at is not None):
        raise ScopeConflict("experiment session is not active")
    assignment = db.get(ExperimentAssignment, session.experiment_assignment_id)
    student = db.get(User, session.student_user_id)
    if assignment is None or student is None or (require_active and not student.is_active):
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
        session = resolve_experiment_session(db, device, explicit_session_id, require_active=False)
        # Explicitly scoped delayed data remains with the original owner. Formal
        # records outside the recorded use interval remain quarantined.
        if not is_demo_session(db, session) and (
            _utc(observed_at) < _utc(session.started_at)
            or (session.ended_at and _utc(observed_at) > _utc(session.ended_at))
        ):
            return None
        return session.id
    try:
        session = find_active_experiment_session(db, device)
    except ScopeConflict:
        return None
    if (
        session is None
        or not is_demo_session(db, session)
        or _utc(observed_at) < _utc(session.started_at)
    ):
        return None
    return session.id


def session_package_version_id(db, session, requested=None):
    """Only new session snapshots are authoritative; legacy test scopes are explicit."""
    from app.experiment_packages.loader import ExperimentPackageLoadError

    assignment = db.get(ExperimentAssignment, session.experiment_assignment_id)
    pinned = session.experiment_version_id
    if pinned is None:
        if not session.is_test_data:
            raise ExperimentPackageLoadError("historical session has no pinned package; start anew")
        pinned = assignment.experiment_version_id if assignment else None
    if requested and pinned and requested != pinned:
        raise ScopeViolation("requested package differs from the session snapshot")
    return pinned or requested
