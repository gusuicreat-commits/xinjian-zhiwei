"""Conservative test provenance for newly derived records.

Callers pass flags from resolved server-side sources, never client assertions of
source identity. None means an expected source could not be verified. Historical
rows are not rewritten by this helper.
"""


def derive_test_flag(*source_flags: bool | None, explicit: bool = False) -> bool:
    """Only explicitly formal, verified sources can produce a formal record."""
    return explicit or not source_flags or any(flag is not False for flag in source_flags)


def diagnosis_scope_test_flag(db, device, context):
    """Resolve recorded scope, without changing unscoped offline fixture semantics."""
    from app.models.classroom import Classroom, ExperimentAssignment, ExperimentSession, User
    from app.services.data_scope import is_demo_device

    scope = context.feedback_scope
    if scope is None:
        return False
    if not isinstance(scope, dict) or scope.get('device_id') != device.id:
        return True
    session = db.get(ExperimentSession, scope.get('experiment_session_id'), populate_existing=True)
    if session is None or session.device_id != device.id or (
        session.student_user_id != scope.get('student_user_id')
    ):
        return True
    student = db.get(User, session.student_user_id, populate_existing=True)
    assignment = db.get(
        ExperimentAssignment, session.experiment_assignment_id, populate_existing=True,
    )
    classroom = (db.get(Classroom, assignment.class_id, populate_existing=True)
                 if assignment else None)
    return derive_test_flag(
        is_demo_device(device), session.is_test_data,
        student.is_test_data if student else None,
        assignment.is_test_data if assignment else None,
        classroom.is_test_data if classroom else None,
    )
