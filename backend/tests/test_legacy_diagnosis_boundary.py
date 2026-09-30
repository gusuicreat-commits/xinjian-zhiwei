from sqlalchemy import func, select

from app.core.security import hash_device_token
from app.models import Device, DiagnosisResult


def test_empty_telemetry_demo_diagnosis_retains_test_provenance(api_context):
    response = api_context['client'].post(
        '/api/v1/diagnosis/devices/phase2-test-device/run',
        headers=api_context['headers'], json={'lookback_seconds': 60},
    )
    assert response.status_code == 201
    assert response.json()['is_test_data'] is True


def test_legacy_diagnosis_rechecks_token_after_freeze(api_context, monkeypatch):
    from app.api.v1.routes import diagnosis

    freeze = diagnosis.freeze

    def rotated(*args):
        context = freeze(*args)
        with api_context['session_factory']() as db:
            db.scalar(select(Device)).token_hash = hash_device_token('rotated', iterations=1000)
            db.commit()
        return context

    monkeypatch.setattr(diagnosis, 'freeze', rotated)
    response = api_context['client'].post(
        '/api/v1/diagnosis/devices/phase2-test-device/run',
        headers=api_context['headers'], json={'lookback_seconds': 60},
    )
    assert response.status_code == 401
    with api_context['session_factory']() as db:
        assert db.scalar(select(func.count()).select_from(DiagnosisResult)) == 0


def test_legacy_diagnosis_rechecks_account_session_after_freeze(api_context, monkeypatch):
    from sqlalchemy import update
    from test_student_write_authorization import account_identity

    from app.api.v1.routes import diagnosis
    from app.models.base import utc_now
    from app.models.classroom import AuthSession

    with api_context['session_factory']() as db:
        account_identity(db)
    login = api_context['client'].post('/api/v1/auth/session', json={
        'username': 'phase2-test-student', 'password': 'synthetic-password',
    })
    headers = {**api_context['headers'], 'Authorization': 'Bearer ' + login.json()['access_token']}
    freeze = diagnosis.freeze

    def revoked(*args):
        context = freeze(*args)
        with api_context['session_factory']() as db:
            db.execute(update(AuthSession).values(revoked_at=utc_now()))
            db.commit()
        return context

    monkeypatch.setattr(diagnosis, 'freeze', revoked)
    response = api_context['client'].post(
        '/api/v1/diagnosis/devices/phase2-test-device/run', headers=headers,
        json={'lookback_seconds': 60},
    )
    assert response.status_code == 401
    with api_context['session_factory']() as db:
        assert db.scalar(select(func.count()).select_from(DiagnosisResult)) == 0


def test_guidance_rechecks_after_lifecycle_wait(api_context, monkeypatch):
    from contextlib import contextmanager

    from app.services import guidance

    created = api_context['client'].post(
        '/api/v1/diagnosis/devices/phase2-test-device/run',
        headers=api_context['headers'], json={'lookback_seconds': 60},
    )
    lifecycle_lock = guidance.lifecycle_lock

    @contextmanager
    def revoked_wait(db, diagnosis):
        with lifecycle_lock(db, diagnosis):
            device = db.get(Device, diagnosis.device_id)
            device.token_hash = hash_device_token('rotated', iterations=1000)
            db.commit()
            yield

    monkeypatch.setattr(guidance, 'lifecycle_lock', revoked_wait)
    response = api_context['client'].post(
        f"/api/v1/diagnosis/results/{created.json()['id']}/guidance",
        headers=api_context['headers'],
    )
    assert response.status_code == 401


def test_guidance_constructs_one_atomic_business_transaction(api_context):
    from shared_student_authorization import demo_student_actor
    from sqlalchemy import event
    from test_diagnosis_workflow import _add_failure_log

    from app.diagnosis.schemas import DiagnosisRunRequest
    from app.models import ExperimentSession
    from app.services.diagnosis import diagnose, save_diagnosis_result
    from app.services.diagnosis_checks import freeze
    from app.services.guidance import generate_guidance

    _add_failure_log(api_context)
    with api_context['session_factory']() as db:
        device = db.scalar(select(Device))
        session = db.scalar(select(ExperimentSession))
        context = freeze(db, device, session, DiagnosisRunRequest(lookback_seconds=60))
        diagnosis = save_diagnosis_result(db, device, context, diagnose(context))
        identity = demo_student_actor(db, device)
        commits = []
        event.listen(db, 'after_commit', lambda _: commits.append(1))
        result = generate_guidance(db, device, diagnosis, student_actor=identity)
        assert result
        assert diagnosis.episode_id
        assert commits == [1]


def test_scope_provenance_uses_verified_sources_and_keeps_offline_meaning(api_context):
    from datetime import datetime, timezone

    from app.diagnosis.schemas import DiagnosisContext
    from app.models import Classroom, ExperimentAssignment, ExperimentSession, User
    from app.services.provenance import diagnosis_scope_test_flag

    with api_context['session_factory']() as db:
        device = db.scalar(select(Device))
        session = db.scalar(select(ExperimentSession))
        student = db.get(User, session.student_user_id)
        assignment = db.get(ExperimentAssignment, session.experiment_assignment_id)
        classroom = db.get(Classroom, assignment.class_id)
        device.device_type = 'physical-device'
        device.metadata_json = {}
        for source in (student, session, assignment, classroom):
            source.is_test_data = False
        db.commit()
        context = DiagnosisContext(
            device_id=device.device_key, evaluated_at=datetime.now(timezone.utc), last_seen_at=None,
        )
        assert diagnosis_scope_test_flag(db, device, context) is False
        context.feedback_scope = {'device_id': device.id, 'student_user_id': student.id,
                                  'experiment_session_id': session.id}
        assert diagnosis_scope_test_flag(db, device, context) is False
        for source in (student, session, assignment, classroom):
            source.is_test_data = True
            db.commit()
            assert diagnosis_scope_test_flag(db, device, context) is True
            source.is_test_data = False
            db.commit()
        device.device_type = 'test-fixture'
        db.commit()
        assert diagnosis_scope_test_flag(db, device, context) is True
        device.device_type = 'physical-device'
        db.commit()
        context.feedback_scope['student_user_id'] = 'unverified-user'
        assert diagnosis_scope_test_flag(db, device, context) is True
