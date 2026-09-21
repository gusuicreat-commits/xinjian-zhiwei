"""Independent connections, durable checkpoints and no production database fallback."""

import os
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import uuid4

import pytest
from sqlalchemy import func, select
from test_diagnosis_checks import check, ingest
from test_teaching_materials import start

from app.evaluation.workflow_environment import workflow_environment
from app.models import DiagnosisCheck, DiagnosisResult, DiagnosisWorkflowRun


@pytest.fixture
def pg_env():
    dsn = os.getenv("XINJIAN_EVAL_POSTGRES_DSN")
    if not dsn:
        pytest.skip("requires explicitly selected test PostgreSQL")
    with workflow_environment("dht11_temperature_humidity", postgres_dsn=dsn) as env:
        yield env


@pytest.mark.parametrize("same_identity", [True, False])
def test_concurrent_checks_share_one_frozen_result(pg_env, same_identity):
    env = pg_env
    first = start(env)
    ingest(env)
    identity = str(uuid4())
    barrier = Barrier(2)

    def worker():
        barrier.wait(timeout=10)
        return check(
            env,
            request_id=identity if same_identity else str(uuid4()),
            baseline_id=first["diagnosis_result_id"],
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: worker(), range(2)))
    assert all(r.status_code == 201 for r in results), [r.text for r in results]
    assert results[0].json()["diagnosis_result_id"] == results[1].json()["diagnosis_result_id"]
    assert results[0].json()["check"]["issues"] == results[1].json()["check"]["issues"]
    with env.sessions() as db:
        assert db.scalar(select(func.count()).select_from(DiagnosisResult)) == 2
        assert db.scalar(select(func.count()).select_from(DiagnosisWorkflowRun)) == 2


def test_restart_after_graph_failure_keeps_input_and_original_identity(pg_env, monkeypatch):
    env = pg_env
    ingest(env)
    graph = env.app.state.diagnosis_graph
    original = graph.invoke

    def fail(*args, **kwargs):
        raise RuntimeError("synthetic worker interruption before graph start")

    monkeypatch.setattr(graph, "invoke", fail)
    identity = str(uuid4())
    assert check(env, request_id=identity).status_code == 503
    with env.sessions() as db:
        frozen = db.scalar(select(DiagnosisCheck)).context_snapshot
    ingest(env)  # Arrives after snapshot; retry must not switch its input.
    monkeypatch.setattr(graph, "invoke", original)
    env.restart_graph()
    result = check(env, request_id=identity)
    assert result.status_code == 201, result.text
    env.restart_graph()
    replay = check(env, request_id=identity)
    assert replay.json()["check"] == result.json()["check"]
    with env.sessions() as db:
        diagnosis = db.scalar(select(DiagnosisResult))
        assert diagnosis.context_snapshot["logs"] == frozen["logs"]
        assert db.scalar(select(func.count()).select_from(DiagnosisResult)) == 1


def test_restart_after_business_commit_does_not_repeat_provider_or_diagnosis(pg_env, monkeypatch):
    from app.services import diagnosis_checks as service

    env = pg_env
    ingest(env)
    identity = str(uuid4())
    with monkeypatch.context() as patch:

        def fail(*args):
            raise RuntimeError("synthetic lost receipt")

        patch.setattr(service, "comparison", fail)
        assert check(env, request_id=identity).status_code == 503
    calls = len(env.provider.calls)
    env.restart_graph()
    assert check(env, request_id=identity).status_code == 201
    assert len(env.provider.calls) == calls
    with env.sessions() as db:
        assert db.scalar(select(func.count()).select_from(DiagnosisResult)) == 1


def test_new_check_racing_resolution_preserves_evidence_revision_and_late_status(pg_env):
    from app.models import DiagnosisFeedback
    from app.services.diagnosis_episode import issue_links

    env = pg_env
    first = start(env)
    ingest(env)
    barrier = Barrier(2)

    def checking():
        barrier.wait(timeout=10)
        return check(env, baseline_id=first["diagnosis_result_id"])

    def resolving():
        barrier.wait(timeout=10)
        return env.request(
            "POST",
            f"/api/v1/student/diagnoses/{first['diagnosis_result_id']}/feedback",
            json={"request_id": str(uuid4()), "action": "resolved"},
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        future_check = pool.submit(checking)
        future_resolve = pool.submit(resolving)
        checked, resolved = future_check.result(), future_resolve.result()
    assert checked.status_code == 201, checked.text
    assert resolved.status_code in {201, 409}, resolved.text
    with env.sessions() as db:
        diagnosis = db.get(DiagnosisResult, checked.json()["diagnosis_result_id"])
        links = issue_links(db, diagnosis)
        assert links
        if resolved.status_code == 409:
            assert all(link.episode.status in {"open", "escalated"} for link in links)
        else:
            # Resolution won before registration. These records were observed before
            # that closure, so they cannot establish a new post-resolution incident.
            assert all(link.episode.status == "resolved" for link in links)
            assert all(link.observation_state == "late_or_unverified" for link in links)
        assert db.scalar(select(func.count()).select_from(DiagnosisResult)) == 2
        applied = list(
            db.scalars(
                select(DiagnosisFeedback).where(DiagnosisFeedback.processing_status == "applied")
            )
        )
        assert len(applied) == int(resolved.status_code == 201)
