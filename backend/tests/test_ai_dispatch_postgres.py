"""Authority must be read after an actual cross-connection quota lock wait."""

import time
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from uuid import uuid4

import pytest
from shared_write_authorization import authorize_write_fixture
from sqlalchemy import event, func, select, text
from sqlalchemy.orm import Session
from test_ai_quota_concurrency import CountingProvider, _diagnosis
from test_migration_r2 import migration_db as migration_db

from app.ai.governance import GovernedAIInvocation
from app.core.config import Settings
from app.models import DiagnosisResult, User
from app.models.ai_usage_reservation import AIUsageReservation
from app.models.base import utc_now
from app.models.classroom import AuthSession
from app.services.auth import AuthorizationDenied, authorize_actor


@pytest.mark.parametrize('replay', [False, True])
def test_revocation_committed_while_quota_lock_waits_blocks_send_and_replay(migration_db, replay):  # noqa: F811
    engine, migrate = migration_db
    migrate('upgrade', 'head')
    settings = Settings(_env_file=None, ai_enabled=True)
    provider = CountingProvider()
    with Session(engine, expire_on_commit=False) as db:
        diagnosis_id = _diagnosis(db).id
        actor = User(username='wait-' + uuid4().hex, display_name='synthetic',
                     password_hash='unused', is_test_data=True)
        db.add(actor)
        authorize_write_fixture(db, actor, 'student')
        identity = actor._actor_context
        if replay:
            GovernedAIInvocation(db, db.get(DiagnosisResult, diagnosis_id), settings,
                                 call_stage='pg-wait').complete_json(
                provider, system_prompt='s', user_prompt='u',
            )
    before_calls = provider.calls
    about_to_wait = Event()
    worker_pid = []

    def observe(_conn, _cursor, statement, _params, _ctx, _many):
        if 'pg_advisory_xact_lock(873421, 91728)' in statement:
            about_to_wait.set()

    def worker():
        with Session(engine, expire_on_commit=False) as db:
            worker_pid.append(db.scalar(text('SELECT pg_backend_pid()')))
            governor = GovernedAIInvocation(
                db, db.get(DiagnosisResult, diagnosis_id), settings, call_stage='pg-wait',
                recheck_access=lambda: authorize_actor(db, identity, 'dashboard.read'),
            )
            with pytest.raises(AuthorizationDenied) as denied:
                governor.complete_json(provider, system_prompt='s', user_prompt='u')
            return denied.value.status_code

    event.listen(engine, 'before_cursor_execute', observe)
    try:
        with engine.connect() as lock, ThreadPoolExecutor(max_workers=1) as pool:
            lock.execute(text('SELECT pg_advisory_lock(873421, 91728)'))
            future = pool.submit(worker)
            try:
                assert about_to_wait.wait(10)
                deadline = time.monotonic() + 10
                with engine.connect().execution_options(isolation_level='AUTOCOMMIT') as monitor:
                    while time.monotonic() < deadline:
                        waiting = monitor.scalar(text(
                            "SELECT wait_event = 'advisory' FROM pg_stat_activity WHERE pid = :pid"
                        ), {'pid': worker_pid[0]})
                        if waiting:
                            break
                        time.sleep(0.01)
                    assert waiting, 'worker must actually wait on PostgreSQL, not only a mock hook'
                with Session(engine) as revoke_db:
                    revoke_db.get(AuthSession, identity.session_id).revoked_at = utc_now()
                    revoke_db.commit()
            finally:
                lock.execute(text('SELECT pg_advisory_unlock(873421, 91728)'))
            assert future.result(timeout=10) == 401
    finally:
        event.remove(engine, 'before_cursor_execute', observe)
    assert provider.calls == before_calls
    with Session(engine) as db:
        assert db.scalar(select(func.count(AIUsageReservation.id))) == int(replay)


@pytest.mark.parametrize('lock_kind', ['quota', 'authority'])
def test_quota_lock_wait_is_bounded_by_total_deadline(migration_db, lock_kind):  # noqa: F811
    engine, migrate = migration_db
    migrate('upgrade', 'head')
    with Session(engine) as db:
        diagnosis_id = _diagnosis(db).id
        actor = User(username='bounded-' + uuid4().hex, display_name='synthetic',
                     password_hash='unused', is_test_data=True)
        db.add(actor)
        authorize_write_fixture(db, actor, 'student')
        identity = actor._actor_context
    provider = CountingProvider()

    def worker():
        from app.ai.governance import AIQuotaDenied

        with Session(engine) as db:
            governor = GovernedAIInvocation(
                db, db.get(DiagnosisResult, diagnosis_id),
                Settings(_env_file=None, ai_enabled=True, ai_total_timeout_seconds=0.15),
                call_stage='bounded-wait',
                recheck_access=lambda: authorize_actor(db, identity, 'dashboard.read'),
            )
            with pytest.raises(AIQuotaDenied) as denied:
                governor.complete_json(provider, system_prompt='s', user_prompt='u')
            assert db.scalar(select(func.count(AIUsageReservation.id))) == 0
            assert db.scalar(text('SHOW lock_timeout')) == '0'
            assert db.scalar(text('SHOW statement_timeout')) == '0'
            return denied.value.code

    with engine.connect() as lock, ThreadPoolExecutor(max_workers=1) as pool:
        if lock_kind == 'quota':
            lock.execute(text('SELECT pg_advisory_lock(873421, 91728)'))
        else:
            lock.execute(select(User).where(User.id == identity.user_id).with_for_update())
        future = pool.submit(worker)
        try:
            # Generous scheduling margin around a 150 ms operation deadline.
            assert future.result(timeout=1.5) == 'AI_DEADLINE_EXCEEDED'
        finally:
            if lock_kind == 'quota':
                lock.execute(text('SELECT pg_advisory_unlock(873421, 91728)'))
            lock.rollback()
    assert provider.calls == 0
    with Session(engine) as db:
        assert db.scalar(select(func.count(AIUsageReservation.id))) == 0
