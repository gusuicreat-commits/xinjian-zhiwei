from contextlib import contextmanager

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from shared_write_authorization import authorize_write_fixture
from sqlalchemy import delete, func, select
from test_diagnosis_workflow import _settings

from app.ai.diagnosis_graph import build_diagnosis_graph
from app.core.security import hash_device_token
from app.diagnosis.workflow_schemas import DiagnosisWorkflowStartRequest
from app.models import Device, ExperimentSession, User
from app.models.base import utc_now
from app.models.classroom import AuthSession, Enrollment, ExperimentAssignment, user_roles
from app.models.diagnosis_check import DiagnosisCheck
from app.models.diagnosis_workflow import DiagnosisWorkflowRun
from app.services.auth import AuthorizationDenied
from app.services.diagnosis_checks import run_check
from app.services.student_authorization import StudentActorContext


def account_identity(db):
    session = db.scalar(select(ExperimentSession))
    user = authorize_write_fixture(db, db.get(User, session.student_user_id), 'student')
    assignment = db.get(ExperimentAssignment, session.experiment_assignment_id)
    db.add(Enrollment(user_id=user.id, class_id=assignment.class_id, status='active'))
    db.commit()
    return StudentActorContext(session.device_id, session.id, account=user._actor_context)


def revoke(db, identity, kind):
    if kind == 'session':
        db.get(AuthSession, identity.account.session_id).revoked_at = utc_now()
    elif kind == 'role':
        db.execute(delete(user_roles).where(user_roles.c.user_id == identity.account.user_id))
    elif kind == 'enrollment':
        db.execute(delete(Enrollment).where(Enrollment.user_id == identity.account.user_id))
    else:
        db.get(Device, identity.device_id).token_hash = hash_device_token(
            'rotated', iterations=1000,
        )
    db.commit()


@pytest.mark.parametrize('kind', ['session', 'role', 'enrollment', 'device_token'])
def test_check_revalidates_after_wait_without_new_business_rows(api_context, monkeypatch, kind):
    from shared_student_authorization import demo_student_actor

    from app.services.data_scope import ScopeViolation

    with api_context['session_factory']() as db:
        device = db.scalar(select(Device))
        session = db.scalar(select(ExperimentSession))
        identity = (demo_student_actor(db, device) if kind == 'device_token'
                    else account_identity(db))

        @contextmanager
        def revoked_wait(*_):
            revoke(db, identity, kind)
            yield

        monkeypatch.setattr('app.services.student_feedback.feedback_lock', revoked_wait)
        with pytest.raises((AuthorizationDenied, ScopeViolation)):
            run_check(db, build_diagnosis_graph(InMemorySaver()), device, _settings(),
                      DiagnosisWorkflowStartRequest(lookback_seconds=60), session,
                      student_actor=identity)
        db.rollback()
        assert db.scalar(select(func.count()).select_from(DiagnosisCheck)) == 0
        assert db.scalar(select(func.count()).select_from(DiagnosisWorkflowRun)) == 0


def test_check_revalidates_between_snapshot_and_command_write(api_context, monkeypatch):
    from app.services import diagnosis_checks

    with api_context['session_factory']() as db:
        identity = account_identity(db)
        device = db.get(Device, identity.device_id)
        session = db.get(ExperimentSession, identity.session_id)
        freeze = diagnosis_checks.freeze

        def revoked_snapshot(*args):
            context = freeze(*args)
            revoke(db, identity, 'session')
            return context

        monkeypatch.setattr(diagnosis_checks, 'freeze', revoked_snapshot)
        with pytest.raises(AuthorizationDenied):
            run_check(db, build_diagnosis_graph(InMemorySaver()), device, _settings(),
                      DiagnosisWorkflowStartRequest(lookback_seconds=60), session,
                      student_actor=identity)
        db.rollback()
        assert db.scalar(select(func.count()).select_from(DiagnosisCheck)) == 0
        assert db.scalar(select(func.count()).select_from(DiagnosisWorkflowRun)) == 0
