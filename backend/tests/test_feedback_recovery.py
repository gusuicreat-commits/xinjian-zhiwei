"""Server-owned feedback recovery survives loss of all browser retry state."""

import os
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from sqlalchemy import select
from test_feedback_reliability import live_workflow

from app.evaluation.workflow_environment import DEVICE_KEY
from app.evaluation.workflow_runner import snapshot
from app.models import DiagnosisFeedback, DiagnosisResult, ExperimentSession, User

RECOVERY = "/api/v1/student/feedback-recovery"


@pytest.fixture(params=["sqlite", "postgres"])
def recovery_env(request):
    dsn = os.getenv("XINJIAN_EVAL_POSTGRES_DSN") if request.param == "postgres" else None
    if request.param == "postgres" and not dsn:
        pytest.skip("XINJIAN_EVAL_POSTGRES_DSN not configured")
    with live_workflow(dsn) as env:
        yield env


def make_pending(env, monkeypatch, payload):
    import app.services.student_feedback as service

    with monkeypatch.context() as patch:

        def fail_before_resume(*args, **kwargs):
            raise RuntimeError("synthetic interruption after accepting feedback")

        patch.setattr(service, "resume_workflow_with_feedback", fail_before_resume)
        assert env.request("POST", env.feedback_path, json=payload).status_code == 503


def test_recovery_after_browser_state_loss_keeps_original_payload(recovery_env, monkeypatch):
    env = recovery_env
    payload = {
        "request_id": str(uuid4()),
        "action": "unresolved",
        "note": "  原始检查记录\n保持原文  ",
    }
    make_pending(env, monkeypatch, payload)
    before = snapshot(env, env.workflow_id)
    # No original request ID or diagnosis ID is supplied by this new client read.
    recovered = env.client.get(RECOVERY, headers=dict(env.headers))
    assert recovered.status_code == 200
    assert recovered.headers["cache-control"] == "no-store"
    (item,) = recovered.json()["pending"]
    assert {key: item[key] for key in payload} == payload
    assert item["processing_status"] == "pending"
    assert item["is_test_data"] is True
    assert recovered.json()["latest_applied"] is None
    assert snapshot(env, env.workflow_id) == before
    assert env.request("GET", RECOVERY).json() == recovered.json()
    assert snapshot(env, env.workflow_id) == before

    response = env.request(
        "POST",
        f"/api/v1/student/diagnoses/{item['diagnosis_result_id']}/feedback",
        json={key: item[key] for key in payload},
    )
    assert response.status_code == 201
    after = snapshot(env, env.workflow_id)
    assert after["resume_count"] == 1
    assert after["feedback_ids"] == before["feedback_ids"]
    final = env.request("GET", RECOVERY).json()
    assert final["pending"] == []
    assert final["latest_applied"]["request_id"] == payload["request_id"]
    assert final["latest_applied"]["processing_status"] == "applied"
    assert snapshot(env, env.workflow_id) == after


def test_recovery_finds_pending_from_an_earlier_diagnosis(recovery_env, monkeypatch):
    env = recovery_env
    make_pending(env, monkeypatch, {"request_id": str(uuid4()), "action": "unresolved"})
    original = env.request("GET", RECOVERY).json()["pending"][0]
    started = env.request("POST", f"/api/v1/diagnosis-workflows/devices/{DEVICE_KEY}", json={})
    assert started.status_code == 201
    assert started.json()["diagnosis_result_id"] != original["diagnosis_result_id"]
    assert env.request("GET", RECOVERY).json()["pending"] == [original]


def test_recovery_restores_applied_receipt_without_repeating_work(recovery_env, monkeypatch):
    import app.api.v1.routes.student as route

    env = recovery_env
    original = route.submit_student_feedback

    def lose_ack(*args, **kwargs):
        original(*args, **kwargs)
        raise RuntimeError("synthetic lost successful acknowledgement")

    with monkeypatch.context() as patch:
        patch.setattr(route, "submit_student_feedback", lose_ack)
        payload = {"request_id": str(uuid4()), "action": "resolved", "note": "合成解决反馈"}
        assert env.request("POST", env.feedback_path, json=payload).status_code == 503
    before = snapshot(env, env.workflow_id)
    with env.sessions() as db:
        db.get(ExperimentSession, env.session_id).status = "completed"
        db.commit()
    recovered = env.request("GET", RECOVERY)
    assert recovered.status_code == 200
    assert recovered.json()["pending"] == []
    item = recovered.json()["latest_applied"]
    assert {key: item[key] for key in payload} == payload
    assert item["id"] == before["feedback_ids"][0]
    assert snapshot(env, env.workflow_id) == before


def test_recovery_does_not_disclose_another_students_request(recovery_env, monkeypatch):
    env = recovery_env
    make_pending(
        env,
        monkeypatch,
        {"request_id": str(uuid4()), "action": "unresolved", "note": "private note"},
    )
    foreign = env.other_student_headers()
    before = snapshot(env, env.workflow_id)
    response = env.request("GET", RECOVERY, headers=foreign)
    assert response.status_code == 200
    assert response.json() == {"pending": [], "latest_applied": None, "has_more_pending": False}
    assert snapshot(env, env.workflow_id) == before

    # A corrupted feedback scope must not expose the original diagnosis through
    # this endpoint, even when the feedback row itself claims the other session.
    with env.sessions() as db:
        db.scalar(select(DiagnosisFeedback)).experiment_session_id = foreign[
            "X-Experiment-Session-ID"
        ]
        db.commit()
    before = snapshot(env, env.workflow_id)
    rejected = env.request("GET", RECOVERY, headers=foreign)
    assert rejected.status_code == 403
    assert "private note" not in rejected.text
    assert snapshot(env, env.workflow_id) == before


def test_recovery_requires_valid_device_session_and_active_student(recovery_env):
    env = recovery_env
    before = snapshot(env, env.workflow_id)
    missing = {k: v for k, v in env.headers.items() if k != "X-Experiment-Session-ID"}
    assert env.client.get(RECOVERY, headers=missing).status_code == 422
    assert (
        env.request(
            "GET", RECOVERY, headers={**env.headers, "X-Device-Token": "invalid"}
        ).status_code
        == 401
    )
    assert (
        env.request(
            "GET", RECOVERY, headers={**env.headers, "X-Experiment-Session-ID": str(uuid4())}
        ).status_code
        == 403
    )
    with env.sessions() as db:
        session = db.get(ExperimentSession, env.session_id)
        db.get(User, session.student_user_id).is_active = False
        db.commit()
    assert env.request("GET", RECOVERY).status_code == 403
    assert snapshot(env, env.workflow_id) == before


def test_recovery_ignores_unscoped_history_and_bounds_backlog(api_context):
    client, headers = api_context["client"], api_context["headers"]
    diagnosis = client.post(
        "/api/v1/diagnosis/devices/phase2-test-device/run", headers=headers, json={}
    ).json()
    now = datetime.now(timezone.utc)
    with api_context["session_factory"]() as db:
        template = db.get(DiagnosisResult, diagnosis["id"])
        old = DiagnosisFeedback(
            device_id=template.device_id,
            diagnosis_result_id=template.id,
            action="resolved",
            is_test_data=True,
        )
        db.add(old)
        # Synthetic backlog across separate diagnoses. The read endpoint must
        # neither infer legacy identities nor discard entries beyond its limit.
        for index in range(21):
            record = DiagnosisResult(
                device_id=template.device_id,
                evaluated_at=now,
                ruleset_version=template.ruleset_version,
                ruleset_hash=template.ruleset_hash,
                input_fingerprint=template.input_fingerprint,
                matched_rules=[],
                evidence=[],
                context_snapshot=template.context_snapshot,
                is_test_data=True,
            )
            db.add(record)
            db.flush()
            db.add(
                DiagnosisFeedback(
                    device_id=record.device_id,
                    diagnosis_result_id=record.id,
                    experiment_session_id=api_context["experiment_session_id"],
                    request_id=str(uuid4()),
                    action="unresolved",
                    note=str(index),
                    processing_status="pending",
                    is_test_data=True,
                    created_at=now + timedelta(seconds=index),
                )
            )
        db.commit()
    response = client.get(RECOVERY, headers=headers)
    assert response.status_code == 200
    data = response.json()
    assert data["latest_applied"] is None
    assert data["has_more_pending"] is True
    assert [item["note"] for item in data["pending"]] == [str(i) for i in range(20)]
    with api_context["session_factory"]() as db:
        assert db.query(DiagnosisFeedback).count() == 22
        legacy = db.scalar(select(DiagnosisFeedback).where(DiagnosisFeedback.request_id.is_(None)))
        assert legacy.experiment_session_id is None and legacy.processing_status is None
