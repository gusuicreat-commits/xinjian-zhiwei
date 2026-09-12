"""Retry boundaries: acknowledgement loss, pending requests, and server-recorded ownership."""

import json
import os
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import datetime, timezone
from uuid import uuid4

import pytest
from sqlalchemy import select

from app.evaluation.workflow_environment import DEVICE_KEY, workflow_environment
from app.evaluation.workflow_runner import DATA, snapshot
from app.models import DiagnosisFeedback, DiagnosisResult, ExperimentSession


@contextmanager
def live_workflow(dsn=None):
    case = next(
        c for c in json.loads((DATA / "workflow_inputs.json").read_text()) if c["id"] == "dht-valid"
    )
    with workflow_environment(case["package"], "valid", dsn) as env:
        now = datetime.now(timezone.utc).isoformat()
        batch = {
            "protocolVersion": "1.0",
            "schemaVersion": "1",
            "requestId": str(uuid4()),
            "bootId": "feedback-reliability",
            "sequenceNo": 1,
            "sentAt": now,
            "isTestData": True,
            "records": [{**r, "occurredAt": now} for r in case["records"]],
        }
        assert env.request("POST", "/api/v1/device/ingest", json=batch).status_code == 201
        started = env.request(
            "POST",
            f"/api/v1/diagnosis-workflows/devices/{DEVICE_KEY}",
            json={"question": "请解释现有证据"},
        )
        assert started.status_code == 201
        assert started.json()["status"] == "waiting_feedback"
        env.workflow_id = started.json()["id"]
        env.feedback_path = (
            f"/api/v1/student/diagnoses/{started.json()['diagnosis_result_id']}/feedback"
        )
        yield env


def test_lost_http_acknowledgement_replays_without_advancing(monkeypatch):
    import app.api.v1.routes.student as route

    original = route.submit_student_feedback
    with live_workflow() as env:

        def lose_ack(*args, **kwargs):
            original(*args, **kwargs)
            raise RuntimeError("synthetic lost response after committed feedback")

        monkeypatch.setattr(route, "submit_student_feedback", lose_ack)
        payload = {"request_id": str(uuid4()), "action": "unresolved"}
        assert env.request("POST", env.feedback_path, json=payload).status_code == 503
        before = snapshot(env, env.workflow_id)
        monkeypatch.setattr(route, "submit_student_feedback", original)
        replay = env.request("POST", env.feedback_path, json=payload)
        assert replay.status_code == 201
        assert replay.json()["id"] == before["feedback_ids"][0]
        assert snapshot(env, env.workflow_id) == before


def test_pending_feedback_requires_same_request_and_recovers(monkeypatch):
    import app.services.student_feedback as service

    original = service.resume_workflow_with_feedback
    with live_workflow() as env:

        def fail_resume(*args, **kwargs):
            raise RuntimeError("synthetic failure before graph resume")

        monkeypatch.setattr(service, "resume_workflow_with_feedback", fail_resume)
        payload = {"request_id": str(uuid4()), "action": "unresolved"}
        assert env.request("POST", env.feedback_path, json=payload).status_code == 503
        pending = snapshot(env, env.workflow_id)
        new = {**payload, "request_id": str(uuid4())}
        assert env.request("POST", env.feedback_path, json=new).status_code == 409
        assert snapshot(env, env.workflow_id) == pending
        monkeypatch.setattr(service, "resume_workflow_with_feedback", original)
        response = env.request("POST", env.feedback_path, json=payload)
        assert response.status_code == 201
        after = snapshot(env, env.workflow_id)
        assert len(after["feedback_ids"]) == 1
        assert after["resume_count"] == 1
        with env.sessions() as db:
            assert db.scalar(select(DiagnosisFeedback)).processing_status == "applied"


def test_checkpoint_reached_next_pause_before_business_ack_is_reconciled(monkeypatch):
    import app.services.diagnosis_workflow as service

    original = service._sync_business_record
    with live_workflow() as env:

        def fail_sync(*args, **kwargs):
            raise RuntimeError("synthetic failure after graph reached next interrupt")

        monkeypatch.setattr(service, "_sync_business_record", fail_sync)
        payload = {"request_id": str(uuid4()), "action": "unresolved"}
        assert env.request("POST", env.feedback_path, json=payload).status_code == 503
        before = snapshot(env, env.workflow_id)
        monkeypatch.setattr(service, "_sync_business_record", original)
        assert env.request("POST", env.feedback_path, json=payload).status_code == 201
        after = snapshot(env, env.workflow_id)
        assert after["state"] == before["state"]
        assert after["provider_calls"] == before["provider_calls"]
        assert after["ai_audit"] == before["ai_audit"]
        assert after["resume_count"] == 1
        assert len(after["feedback_ids"]) == 1


def test_unscoped_historical_diagnosis_is_not_assigned_to_current_student(api_context):
    # Create a normal legacy result, then remove only the server-owned scope to
    # model a pre-migration record. It must not borrow today's session identity.
    response = api_context["client"].post(
        "/api/v1/diagnosis/devices/phase2-test-device/run", headers=api_context["headers"], json={}
    )
    diagnosis_id = response.json()["id"]
    with api_context["session_factory"]() as db:
        diagnosis = db.get(DiagnosisResult, diagnosis_id)
        context = dict(diagnosis.context_snapshot)
        context.pop("feedback_scope")
        diagnosis.context_snapshot = context
        db.commit()
    feedback = api_context["client"].post(
        f"/api/v1/student/diagnoses/{diagnosis_id}/feedback",
        headers=api_context["headers"],
        json={"request_id": str(uuid4()), "action": "resolved"},
    )
    assert feedback.status_code == 403
    with api_context["session_factory"]() as db:
        assert list(db.scalars(select(DiagnosisFeedback))) == []


def test_postgres_concurrent_duplicate_requests_apply_once():
    dsn = os.getenv("XINJIAN_EVAL_POSTGRES_DSN")
    if not dsn:
        pytest.skip("XINJIAN_EVAL_POSTGRES_DSN not configured")
    with live_workflow(dsn) as env:
        payload = {
            "request_id": str(uuid4()),
            "action": "unresolved",
            "note": "concurrent same submission",
        }
        before = snapshot(env, env.workflow_id)

        def send(_):
            return env.client.post(env.feedback_path, headers=env.headers, json=payload)

        with ThreadPoolExecutor(max_workers=4) as pool:
            responses = list(pool.map(send, range(4)))
        assert [r.status_code for r in responses] == [201] * 4
        assert all(r.json() == responses[0].json() for r in responses)
        after = snapshot(env, env.workflow_id)
        assert len(after["feedback_ids"]) == 1
        assert after["resume_count"] == 1
        assert after["provider_calls"] - before["provider_calls"] == 2


def test_completed_session_can_replay_but_cannot_submit_new_feedback():
    with live_workflow() as env:
        payload = {"request_id": str(uuid4()), "action": "resolved"}
        first = env.request("POST", env.feedback_path, json=payload)
        assert first.status_code == 201
        with env.sessions() as db:
            session = db.get(ExperimentSession, env.session_id)
            session.status = "completed"
            db.commit()
        before = snapshot(env, env.workflow_id)
        replay = env.request("POST", env.feedback_path, json=payload)
        assert replay.status_code == 201
        assert replay.json() == first.json()
        new = {**payload, "request_id": str(uuid4())}
        assert env.request("POST", env.feedback_path, json=new).status_code == 409
        assert snapshot(env, env.workflow_id) == before


@pytest.mark.parametrize("backend", ["sqlite", "postgres"])
@pytest.mark.parametrize("action", ["unresolved", "resolved", "request_teacher_help"])
def test_closed_session_can_acknowledge_already_consumed_pending_feedback(
    monkeypatch, backend, action
):
    import app.services.diagnosis_workflow as service

    dsn = os.getenv("XINJIAN_EVAL_POSTGRES_DSN") if backend == "postgres" else None
    if backend == "postgres" and not dsn:
        pytest.skip("XINJIAN_EVAL_POSTGRES_DSN not configured")
    original = service._sync_business_record
    with live_workflow(dsn) as env:

        def fail_sync(*args, **kwargs):
            raise RuntimeError("synthetic business acknowledgement loss after checkpoint")

        monkeypatch.setattr(service, "_sync_business_record", fail_sync)
        payload = {"request_id": str(uuid4()), "action": action}
        assert env.request("POST", env.feedback_path, json=payload).status_code == 503
        monkeypatch.setattr(service, "_sync_business_record", original)
        with env.sessions() as db:
            db.get(ExperimentSession, env.session_id).status = "completed"
            db.commit()
        before = snapshot(env, env.workflow_id)
        assert len(before["feedback_ids"]) == 1
        assert before["feedback_requests"][0]["processing_status"] == "pending"
        assert before["resume_count"] == 0

        def forbid_graph_execution(*args, **kwargs):
            pytest.fail("closed-session acknowledgement must not execute the graph")

        monkeypatch.setattr(env.app.state.diagnosis_graph, "invoke", forbid_graph_execution)
        retried = env.request("POST", env.feedback_path, json=payload)
        assert retried.status_code == 201
        assert retried.json()["id"] == before["feedback_ids"][0]
        after = snapshot(env, env.workflow_id)
        assert after["state"] == before["state"]
        assert after["provider_calls"] == before["provider_calls"]
        assert after["ai_audit"] == before["ai_audit"]
        assert after["feedback_ids"] == before["feedback_ids"]
        assert after["resume_count"] == 1
        assert after["feedback_requests"][0]["processing_status"] == "applied"
        assert (
            after["status"]
            == {
                "unresolved": "waiting_feedback",
                "resolved": "completed",
                "request_teacher_help": "waiting_teacher",
            }[action]
        )
        assert env.request("POST", env.feedback_path, json=payload).json() == retried.json()
        assert snapshot(env, env.workflow_id) == after


@pytest.mark.parametrize("backend", ["sqlite", "postgres"])
def test_closed_session_cannot_consume_unapplied_pending_feedback(monkeypatch, backend):
    import app.services.student_feedback as service

    dsn = os.getenv("XINJIAN_EVAL_POSTGRES_DSN") if backend == "postgres" else None
    if backend == "postgres" and not dsn:
        pytest.skip("XINJIAN_EVAL_POSTGRES_DSN not configured")
    original = service.resume_workflow_with_feedback
    with live_workflow(dsn) as env:

        def fail_before_resume(*args, **kwargs):
            raise RuntimeError("synthetic failure before feedback is consumed")

        monkeypatch.setattr(service, "resume_workflow_with_feedback", fail_before_resume)
        payload = {"request_id": str(uuid4()), "action": "unresolved"}
        assert env.request("POST", env.feedback_path, json=payload).status_code == 503
        monkeypatch.setattr(service, "resume_workflow_with_feedback", original)
        with env.sessions() as db:
            db.get(ExperimentSession, env.session_id).status = "completed"
            db.commit()
        before = snapshot(env, env.workflow_id)
        assert before["state"]["attempt_count"] == 0
        assert before["feedback_requests"][0]["processing_status"] == "pending"

        def forbid_graph_execution(*args, **kwargs):
            pytest.fail("closed-session pending feedback must not execute the graph")

        monkeypatch.setattr(env.app.state.diagnosis_graph, "invoke", forbid_graph_execution)
        assert env.request("POST", env.feedback_path, json=payload).status_code == 409
        assert snapshot(env, env.workflow_id) == before


@pytest.mark.parametrize("backend", ["sqlite", "postgres"])
@pytest.mark.parametrize(
    "write_method,write_index",
    [("put", index) for index in range(1, 7)] + [("put_writes", index) for index in range(1, 9)],
)
def test_interrupted_checkpoint_write_finishes_one_feedback(
    monkeypatch, write_method, write_index, backend
):
    dsn = os.getenv("XINJIAN_EVAL_POSTGRES_DSN") if backend == "postgres" else None
    if backend == "postgres" and not dsn:
        pytest.skip("XINJIAN_EVAL_POSTGRES_DSN not configured")
    with live_workflow(dsn) as env:
        graph = env.app.state.diagnosis_graph
        saver = graph.checkpointer
        original = getattr(saver, write_method)
        calls = 0

        def interrupt_one_write(*args, **kwargs):
            nonlocal calls
            calls += 1
            if calls == write_index:
                raise RuntimeError("synthetic checkpoint write interruption")
            return original(*args, **kwargs)

        monkeypatch.setattr(saver, write_method, interrupt_one_write)
        payload = {"request_id": str(uuid4()), "action": "unresolved"}
        first = env.request("POST", env.feedback_path, json=payload)
        assert calls >= write_index
        assert first.status_code == 503
        monkeypatch.setattr(saver, write_method, original)
        retried = env.request("POST", env.feedback_path, json=payload)
        assert retried.status_code == 201
        completed = snapshot(env, env.workflow_id)
        assert completed["status"] == "waiting_feedback"
        assert completed["state"]["attempt_count"] == 1
        assert completed["state"]["node_trace"].count("feedback_handler") == 1
        assert completed["resume_count"] == 1
        assert len(completed["feedback_ids"]) == 1
        assert all(r["processing_status"] == "applied" for r in completed["feedback_requests"])
        assert env.request("POST", env.feedback_path, json=payload).json() == retried.json()
        assert snapshot(env, env.workflow_id) == completed
