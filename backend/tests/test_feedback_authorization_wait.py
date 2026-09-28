"""DATA-01: actual PostgreSQL lock waits must not preserve revoked authority."""

import hashlib
import json
import os
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from sqlalchemy import delete, select, text
from test_business_identity import account_headers
from test_teaching_materials import start

from app.evaluation.workflow_environment import workflow_environment
from app.evaluation.workflow_runner import snapshot
from app.models import (
    AuthSession,
    Classroom,
    Device,
    DiagnosisResult,
    DiagnosisWorkflowRun,
    Enrollment,
    ExperimentAssignment,
    ExperimentSession,
    Permission,
    User,
)
from app.models.classroom import role_permissions, user_roles
from app.services.diagnosis_episode import diagnosis_scope


def account_login(env):
    env.headers = account_headers(
        {
            "session_factory": env.sessions,
            "experiment_session_id": env.session_id,
            "client": env.client,
            "headers": env.headers,
        },
        enrolled=False,
    )


def revoke(env, change):
    with env.sessions() as db:
        session = db.get(ExperimentSession, env.session_id)
        user = db.get(User, session.student_user_id)
        assignment = db.get(ExperimentAssignment, session.experiment_assignment_id)
        if change == "user":
            user.is_active = False
        elif change == "device":
            db.get(Device, session.device_id).is_active = False
        elif change == "token":
            db.get(Device, session.device_id).token_hash = "revoked"
        elif change == "login":
            db.scalar(
                select(AuthSession).where(AuthSession.user_id == user.id)
            ).revoked_at = datetime.now(timezone.utc)
        elif change == "expired_login":
            db.scalar(select(AuthSession).where(AuthSession.user_id == user.id)).expires_at = (
                datetime.now(timezone.utc) - timedelta(seconds=1)
            )
        elif change == "enrollment":
            db.scalar(select(Enrollment).where(Enrollment.user_id == user.id)).status = "revoked"
        elif change == "classroom":
            db.get(Classroom, assignment.class_id).is_active = False
        elif change == "role":
            db.execute(delete(user_roles).where(user_roles.c.user_id == user.id))
        elif change == "permission":
            permission = db.scalar(select(Permission).where(Permission.code == "feedback.create"))
            db.execute(
                delete(role_permissions).where(role_permissions.c.permission_id == permission.id)
            )
        else:
            raise AssertionError(change)
        db.commit()


@pytest.mark.parametrize("lock_kind", ["feedback", "lifecycle"])
@pytest.mark.parametrize(
    "mode,change",
    [
        ("demo", "user"),
        ("demo", "device"),
        ("demo", "token"),
        ("account", "user"),
        ("account", "login"),
        ("account", "expired_login"),
        ("account", "enrollment"),
        ("account", "classroom"),
        ("account", "role"),
        ("account", "permission"),
    ],
)
def test_revocation_during_lock_wait_has_no_feedback_side_effects(lock_kind, mode, change):
    dsn = os.getenv("XINJIAN_EVAL_POSTGRES_DSN")
    if not dsn:
        pytest.skip("requires explicitly selected test PostgreSQL")
    with workflow_environment("dht11_temperature_humidity", postgres_dsn=dsn) as env:
        first = start(env)
        if mode == "account":
            account_login(env)
        diagnosis_id = first["diagnosis_result_id"]
        lock_input = diagnosis_id
        if lock_kind == "lifecycle":
            with env.sessions() as db:
                lock_input = json.dumps(
                    diagnosis_scope(db.get(DiagnosisResult, diagnosis_id)), sort_keys=True
                )
        key = int.from_bytes(hashlib.sha256(lock_input.encode()).digest()[:8], "big", signed=True)
        before = snapshot(env, first["id"])
        calls = len(env.provider.calls)
        with env.engine.connect().execution_options(isolation_level="AUTOCOMMIT") as holder:
            holder.execute(text("SELECT pg_advisory_lock(:key)"), {"key": key})
            with ThreadPoolExecutor(max_workers=1) as pool:
                pending = pool.submit(
                    env.request,
                    "POST",
                    f"/api/v1/student/diagnoses/{diagnosis_id}/feedback",
                    json={"request_id": str(uuid4()), "action": "resolved"},
                )
                try:
                    deadline = time.monotonic() + 10
                    waiting = False
                    while time.monotonic() < deadline:
                        waiting = holder.scalar(
                            text(
                                "SELECT EXISTS(SELECT 1 FROM pg_locks WHERE locktype='advisory' "
                                "AND NOT granted AND classid=:hi AND objid=:lo)"
                            ),
                            {"hi": (key & ((1 << 64) - 1)) >> 32, "lo": key & ((1 << 32) - 1)},
                        )
                        if waiting or pending.done():
                            break
                        time.sleep(0.01)
                    assert waiting, "request did not reach the real lock wait"
                    revoke(env, change)
                finally:
                    holder.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": key})
                response = pending.result(timeout=15)
        assert response.status_code in {401, 403}, response.text
        assert snapshot(env, first["id"]) == before
        assert len(env.provider.calls) == calls


def test_pending_recovery_rechecks_login_after_workflow_row_wait(monkeypatch):
    from app.services import student_feedback as service

    dsn = os.getenv("XINJIAN_EVAL_POSTGRES_DSN")
    if not dsn:
        pytest.skip("requires explicitly selected test PostgreSQL")
    with workflow_environment("dht11_temperature_humidity", postgres_dsn=dsn) as env:
        first = start(env)
        account_login(env)
        path = f"/api/v1/student/diagnoses/{first['diagnosis_result_id']}/feedback"
        payload = {"request_id": str(uuid4()), "action": "unresolved"}
        with monkeypatch.context() as patch:

            def unavailable(*args, **kwargs):
                raise RuntimeError("synthetic interruption before resume")

            patch.setattr(service, "resume_workflow_with_feedback", unavailable)
            assert env.request("POST", path, json=payload).status_code == 503
        before = snapshot(env, first["id"])
        with env.sessions() as holder:
            holder.scalar(
                select(DiagnosisWorkflowRun)
                .where(DiagnosisWorkflowRun.id == first["id"])
                .with_for_update()
            )
            pid = holder.scalar(text("SELECT pg_backend_pid()"))
            with ThreadPoolExecutor(max_workers=1) as pool:
                pending = pool.submit(env.request, "POST", path, json=payload)
                try:
                    deadline = time.monotonic() + 10
                    waiting = False
                    while time.monotonic() < deadline:
                        waiting = holder.scalar(
                            text(
                                "SELECT EXISTS(SELECT 1 FROM pg_stat_activity "
                                "WHERE :pid = ANY(pg_blocking_pids(pid)))"
                            ),
                            {"pid": pid},
                        )
                        if waiting or pending.done():
                            break
                        time.sleep(0.01)
                    assert waiting, "recovery did not reach workflow row wait"
                    revoke(env, "login")
                finally:
                    holder.rollback()
                response = pending.result(timeout=15)
        assert response.status_code == 401, response.text
        assert snapshot(env, first["id"]) == before


def test_valid_account_can_replay_applied_feedback_after_session_ends():
    with workflow_environment("dht11_temperature_humidity") as env:
        first = start(env)
        account_login(env)
        path = f"/api/v1/student/diagnoses/{first['diagnosis_result_id']}/feedback"
        payload = {"request_id": str(uuid4()), "action": "unresolved"}
        original = env.request("POST", path, json=payload)
        assert original.status_code == 201
        with env.sessions() as db:
            session = db.get(ExperimentSession, env.session_id)
            session.status = "ended"
            session.ended_at = datetime.now(timezone.utc)
            db.commit()
        before = snapshot(env, first["id"])
        replay = env.request("POST", path, json=payload)
        assert replay.status_code == 201 and replay.json() == original.json()
        new = env.request("POST", path, json={**payload, "request_id": str(uuid4())})
        assert new.status_code == 409
        assert snapshot(env, first["id"]) == before
