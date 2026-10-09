"""Independent regressions for the 2026-09-30 whole-project audit."""

import hashlib
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from threading import Event, Lock
from uuid import uuid4

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from shared_write_authorization import authorize_write_fixture
from sqlalchemy import delete, select, text
from test_teaching_materials import start

from app.evaluation.workflow_environment import LOGIN_PASSWORD, workflow_environment
from app.models import DiagnosisResult, InterventionCase, TeachingAssignment, User
from app.models.experiment import ExperimentTemplateVersion
from app.models.intervention import InterventionEvent
from app.services.diagnosis_episode import diagnosis_scope
from app.services.experiment_templates import create_template, transition, update_content


@pytest.fixture
def audit_env():
    dsn = os.getenv("XINJIAN_EVAL_POSTGRES_DSN")
    if not dsn:
        pytest.skip("explicit isolated PostgreSQL required")
    with workflow_environment("dht11_temperature_humidity", postgres_dsn=dsn) as env:
        yield env


def teacher(env):
    response = env.client.post(
        "/api/v1/auth/session",
        json={
            "username": "synthetic-teacher",
            "password": LOGIN_PASSWORD,
        },
    )
    assert response.status_code == 200, response.text
    return {"Authorization": "Bearer " + response.json()["access_token"]}


def content():
    return dict(
        objective="reviewed",
        steps=["one"],
        expected_outputs=["ok"],
        device_profile={"kind": "test"},
        sensor_fields=["temp"],
        safety_notes=["safe"],
    )


@pytest.mark.parametrize("revocation", ["teaching", "session", "permission"])
@pytest.mark.parametrize("operation", ["actions", "problem-resolution"])
def test_teacher_revoked_during_real_lock_wait_cannot_claim(audit_env, revocation, operation):
    env = audit_env
    headers = teacher(env)
    first = start(env)
    response = env.client.post(
        f"/api/v1/teacher-workflow/diagnoses/{first['diagnosis_result_id']}/intervention",
        headers=headers,
    )
    assert response.status_code == 201
    case_id = response.json()["id"]
    episode_id = response.json()["episode_id"]
    from app.models import AuthSession, DiagnosisEpisode
    from app.models.base import utc_now
    from app.models.classroom import user_roles

    with env.sessions() as db:
        revision = db.get(DiagnosisEpisode, episode_id).evidence_revision
    payload = (
        {"action": "claim", "expected_version": 1, "request_id": str(uuid4())}
        if operation == "actions"
        else {"expected_revision": revision, "request_id": str(uuid4())}
    )
    with env.sessions() as db:
        actor = db.scalar(select(User).where(User.username == "synthetic-teacher"))
        authorize_write_fixture(db, actor, "teacher")
        actor_id = actor.id
        scope = json.dumps(
            diagnosis_scope(db.get(DiagnosisResult, first["diagnosis_result_id"])), sort_keys=True
        )
    key = int.from_bytes(hashlib.sha256(scope.encode()).digest()[:8], "big", signed=True)
    with env.engine.connect().execution_options(isolation_level="AUTOCOMMIT") as holder:
        holder.execute(text("SELECT pg_advisory_lock(:key)"), {"key": key})
        with ThreadPoolExecutor(max_workers=1) as pool:
            pending = pool.submit(
                env.client.post,
                f"/api/v1/teacher-workflow/interventions/{case_id}/{operation}",
                headers=headers,
                json=payload,
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
                assert waiting, "must exercise an actual database lock wait"
                with env.sessions() as db:
                    if revocation == "teaching":
                        db.execute(
                            delete(TeachingAssignment).where(TeachingAssignment.user_id == actor_id)
                        )
                    elif revocation == "session":
                        from sqlalchemy import update

                        db.execute(
                            update(AuthSession)
                            .where(AuthSession.user_id == actor_id)
                            .values(revoked_at=utc_now())
                        )
                    else:
                        db.execute(delete(user_roles).where(user_roles.c.user_id == actor_id))
                    db.commit()
            finally:
                holder.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": key})
            response = pending.result(timeout=15)
    assert response.status_code == (401 if revocation == "session" else 403)
    with env.sessions() as db:
        case = db.get(InterventionCase, case_id)
        assert (case.status, case.version_no) == ("open", 1)
        assert (
            db.query(InterventionEvent)
            .filter(
                InterventionEvent.case_id == case_id,
                InterventionEvent.action.in_(["claim", "problem_resolved"]),
            )
            .count()
            == 0
        )
        assert db.get(DiagnosisEpisode, episode_id).status in {"open", "escalated"}


def test_stale_draft_cannot_overwrite_published_content(audit_env):
    env = audit_env
    with env.sessions() as db:
        actor = db.scalar(select(User).where(User.username == "synthetic-teacher"))
        authorize_write_fixture(db, actor, "teacher")
        actor_id = actor.id
        _, version = create_template(
            db,
            actor,
            code="audit",
            title="test",
            description=None,
            version="1",
            content=content(),
            is_test_data=True,
        )
        version_id = version.id
    with env.sessions() as editor, env.sessions() as publisher:
        stale = editor.get(ExperimentTemplateVersion, version_id)
        published = publisher.get(ExperimentTemplateVersion, version_id)
        for state in ("pending", "approved", "published"):
            transition(
                publisher,
                authorize_write_fixture(publisher, publisher.get(User, actor_id), "teacher"),
                published,
                state,
            )
        with pytest.raises(ValueError):
            update_content(
                editor,
                authorize_write_fixture(editor, editor.get(User, actor_id), "teacher"),
                stale,
                {"objective": "unreviewed"},
            )
        editor.rollback()
    with env.sessions() as db:
        version = db.get(ExperimentTemplateVersion, version_id)
        assert version.status == "published"
        assert version.content_json == content()


def test_duplicate_template_returns_conflict(audit_env):
    env = audit_env
    headers = teacher(env)
    payload = dict(
        code="duplicate", title="test", version="1", content=content(), is_test_data=True
    )
    with TestClient(env.app, raise_server_exceptions=False) as client:
        first = client.post("/api/v1/experiments/templates", headers=headers, json=payload)
        second = client.post("/api/v1/experiments/templates", headers=headers, json=payload)
    assert first.status_code == 201
    assert second.status_code == 409


def test_parallel_failed_logins_are_bounded(audit_env, monkeypatch):
    from app.api.v1.routes import auth

    env = audit_env
    release = Event()
    entered = []
    lock = Lock()

    def password_check(*args, **kwargs):
        with lock:
            entered.append(1)
        assert release.wait(10)
        return None

    monkeypatch.setattr(auth, "create_session", password_check)
    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = [
            pool.submit(
                env.client.post,
                "/api/v1/auth/session",
                json={
                    "username": "audit-parallel",
                    "password": "wrong",
                },
            )
            for _ in range(8)
        ]
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline and sum(f.done() for f in futures) < 3:
            time.sleep(0.01)
        release.set()
        responses = [f.result(timeout=10).status_code for f in futures]
    assert len(entered) == 5
    assert sorted(responses) == [401] * 5 + [429] * 3


def test_docs_scripts_are_allowed_without_weakening_json_api(api_context):
    import re

    client = api_context["client"]
    response = client.get("/docs")
    assert response.status_code == 200
    nonce = re.search(r'<script[^>]*nonce="([^"]+)"', response.text)
    assert nonce is not None
    assert f"'nonce-{nonce.group(1)}'" in response.headers["content-security-policy"]
    assert (
        "'unsafe-inline'"
        not in response.headers["content-security-policy"].split("script-src")[1].split(";")[0]
    )
    assert (
        client.get("/api/v1/health")
        .headers["content-security-policy"]
        .startswith("default-src 'none'")
    )


def test_success_does_not_release_other_inflight_logins(audit_env):
    from app.models.login_attempt import LoginAttempt
    from app.services.login_limits import finish_attempt, reserve_attempt

    env = audit_env
    with env.sessions() as first, env.sessions() as second:
        one = reserve_attempt(first, "shared-key", 2, 300)
        two = reserve_attempt(second, "shared-key", 2, 300)
        finish_attempt(first, one, succeeded=True, window_seconds=300)
        first.commit()
        assert second.get(LoginAttempt, two).status == "pending"
        three = reserve_attempt(first, "shared-key", 2, 300)
        assert three != two
        with pytest.raises(HTTPException) as limited:
            reserve_attempt(second, "shared-key", 2, 300)
        assert limited.value.status_code == 429


def test_expired_reservation_cannot_issue_session(audit_env):
    from datetime import timedelta

    from fastapi import HTTPException

    from app.models import AuthSession
    from app.models.base import utc_now
    from app.models.login_attempt import LoginAttempt
    from app.services.auth import create_session
    from app.services.login_limits import finish_attempt, reserve_attempt

    with audit_env.sessions() as db:
        attempt_id = reserve_attempt(db, "late", 5, 300)
        attempt = db.get(LoginAttempt, attempt_id)
        attempt.expires_at = utc_now() - timedelta(seconds=1)
        db.commit()
        before = db.query(AuthSession).count()
        with pytest.raises(HTTPException) as limited:
            create_session(
                db,
                "synthetic-teacher",
                LOGIN_PASSWORD,
                1,
                finalize_success=lambda: finish_attempt(
                    db, attempt_id, succeeded=True, window_seconds=300
                ),
            )
        assert limited.value.status_code == 429
        assert db.query(AuthSession).count() == before


def test_login_limits_survive_separate_processes(audit_env):
    import subprocess

    # Separate interpreters have no shared Python locks or in-memory counters.
    code = """
import sys
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from app.services.login_limits import reserve_attempt
with Session(create_engine(sys.argv[1])) as db:
    try:
        reserve_attempt(db, "process-key", 1, 300)
        print("admitted")
    except HTTPException as e:
        print(e.status_code)
"""
    url = audit_env.engine.url.update_query_dict(
        {"options": f"-csearch_path={audit_env.schema},public"}
    ).render_as_string(hide_password=False)
    results = [
        subprocess.run(
            [sys.executable, "-c", code, url],
            capture_output=True,
            text=True,
            check=True,
            timeout=15,
        ).stdout.strip()
        for _ in range(2)
    ]
    assert results == ["admitted", "429"]


def test_duplicate_template_version_is_conflict(audit_env):
    env = audit_env
    headers = teacher(env)
    response = env.client.post(
        "/api/v1/experiments/templates",
        headers=headers,
        json={
            "code": "duplicate-version",
            "title": "test",
            "version": "1",
            "content": content(),
            "is_test_data": True,
        },
    )
    template_id = response.json()["template_id"]
    with TestClient(env.app, raise_server_exceptions=False) as client:
        response = client.post(
            f"/api/v1/experiments/templates/{template_id}/versions",
            headers=headers,
            json={"version": "1", "content": content()},
        )
    assert response.status_code == 409


def test_concurrent_template_publications_leave_one_current(audit_env):
    from threading import Barrier

    from app.services.experiment_templates import create_template_version

    env = audit_env
    with env.sessions() as db:
        actor = db.scalar(select(User).where(User.username == "synthetic-teacher"))
        authorize_write_fixture(db, actor, "teacher")
        actor_id = actor.id
        template, first = create_template(
            db,
            actor,
            code="parallel-publish",
            title="test",
            description=None,
            version="1",
            content=content(),
            is_test_data=True,
        )
        second = create_template_version(db, actor, template, version="2", content=content())
        ids = [first.id, second.id]
        for version in (first, second):
            for status in ("pending", "approved"):
                transition(db, actor, version, status)
    barrier = Barrier(2)

    def publish(version_id):
        with env.sessions() as db:
            version = db.get(ExperimentTemplateVersion, version_id)
            actor = authorize_write_fixture(db, db.get(User, actor_id), "teacher")
            barrier.wait(timeout=10)
            transition(db, actor, version, "published")

    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(publish, ids))
    with env.sessions() as db:
        statuses = [db.get(ExperimentTemplateVersion, version_id).status for version_id in ids]
        assert sorted(statuses) == ["published", "superseded"]


def test_login_reservations_bound_capacity_and_clean_expired_rows(audit_env, monkeypatch):
    from datetime import timedelta

    from app.models.base import utc_now
    from app.models.login_attempt import LoginAttempt
    from app.services import login_limits

    monkeypatch.setattr(login_limits, "_MAX_ROWS", 2)
    with audit_env.sessions() as db:
        first = login_limits.reserve_attempt(db, "one", 5, 300)
        login_limits.reserve_attempt(db, "two", 5, 300)
        with pytest.raises(HTTPException) as limited:
            login_limits.reserve_attempt(db, "three", 5, 300)
        assert limited.value.status_code == 429
        db.get(LoginAttempt, first).expires_at = utc_now() - timedelta(seconds=1)
        db.commit()
        login_limits.reserve_attempt(db, "three", 5, 300)
        assert db.query(LoginAttempt).count() == 2
        assert db.get(LoginAttempt, first) is None
