"""Recovery and counters must describe observations, not repeated requests."""

from datetime import datetime, timedelta, timezone

import pytest

from app.core.config import Settings
from app.models import Device
from app.services.diagnosis import build_diagnosis_context, diagnose, save_diagnosis_result
from app.services.diagnosis_episode import upsert_episode
from app.services.guidance import generate_guidance


def record(db, device, at, *, failure=True, observation=None, scope=None, status="unknown"):
    context = build_diagnosis_context(db, device, evaluated_at=at)
    if scope:
        context.feedback_scope = {"experiment_session_id": scope}
    if failure:
        from app.diagnosis.schemas import ContextLog

        context.logs = [
            ContextLog(
                id=observation or "failed-log",
                level="ERROR",
                message="fixture",
                event_code="SENSOR_READ_FAILED",
                occurred_at=at,
                is_test_data=False,
            )
        ]
    outcome = diagnose(context)
    if not failure:
        context.normal_assessment = {
            "status": status,
            "checks": [
                {"check": "required_data", "status": "satisfied" if status == "normal" else status}
            ],
        }
        if observation:
            from app.diagnosis.schemas import ContextHeartbeat

            context.heartbeats = [
                ContextHeartbeat(id=observation, observed_at=at, received_at=at, is_test_data=False)
            ]
    return save_diagnosis_result(db, device, context, outcome)


@pytest.mark.parametrize(
    "status,new_data", [("unknown", True), ("abnormal", True), ("normal", False)]
)
def test_insufficient_recovery_evidence_keeps_episode_open(api_context, status, new_data):
    with api_context["session_factory"]() as db:
        device = db.query(Device).one()
        now = datetime.now(timezone.utc)
        device.last_seen_at = now
        first = record(db, device, now)
        episode = upsert_episode(db, device, first, [], Settings())
        following = record(
            db,
            device,
            now + timedelta(seconds=1),
            failure=False,
            status=status,
            observation="new-beat" if new_data else None,
        )
        upsert_episode(db, device, following, [], Settings())
        db.refresh(episode)
        assert episode.status == "open"
        assert episode.resolution_source is None


def test_explicit_fresh_normal_recovers_only_same_session(api_context):
    with api_context["session_factory"]() as db:
        device = db.query(Device).one()
        now = datetime.now(timezone.utc)
        device.last_seen_at = now
        episodes = []
        for scope in ("session-a", "session-b"):
            first = record(db, device, now, scope=scope)
            episodes.append(upsert_episode(db, device, first, [], Settings()))
        following = record(
            db,
            device,
            now + timedelta(seconds=1),
            failure=False,
            status="normal",
            observation="new-beat",
            scope="session-a",
        )
        upsert_episode(db, device, following, [], Settings())
        for item in episodes:
            db.refresh(item)
        assert episodes[0].status == "resolved"
        assert episodes[0].resolution_source == "deterministic_recovery"
        assert episodes[1].status == "open"


def test_same_evidence_preserves_duration_escalation(api_context):
    with api_context["session_factory"]() as db:
        device = db.query(Device).one()
        now = datetime.now(timezone.utc)
        device.last_seen_at = now
        first = record(db, device, now)
        first_history = generate_guidance(db, device, first)[0]
        later = record(db, device, now + timedelta(seconds=301))
        history = generate_guidance(db, device, later)[0]
        assert history.failure_count == first_history.failure_count == 1
        assert history.anomaly_duration_seconds == 301
        assert history.hint_level == 2


@pytest.mark.parametrize(
    "field,value",
    [
        ("experiment_id", "another-experiment"),
        ("experiment_version", "2"),
        ("experiment_version_id", "another-version"),
        ("is_test_data", True),
    ],
)
def test_history_isolated_by_experiment_version_and_test_boundary(api_context, field, value):
    with api_context["session_factory"]() as db:
        device = db.query(Device).one()
        now = datetime.now(timezone.utc)
        device.last_seen_at = now
        first = record(db, device, now)
        generate_guidance(db, device, first)
        episode = upsert_episode(db, device, first, [], Settings())
        later = record(db, device, now + timedelta(seconds=1), observation="new-failure")
        setattr(later, field, value)
        db.commit()
        history = generate_guidance(db, device, later)[0]
        next_episode = upsert_episode(db, device, later, [history], Settings())
        assert history.failure_count == 1
        assert next_episode.id != episode.id


def test_guidance_resets_after_confirmed_recovery_and_between_sessions(api_context):
    with api_context["session_factory"]() as db:
        device = db.query(Device).one()
        now = datetime.now(timezone.utc)
        device.last_seen_at = now
        first = record(db, device, now, scope="session-a")
        generate_guidance(db, device, first)
        record(
            db,
            device,
            now + timedelta(seconds=1),
            failure=False,
            observation="new-beat",
            status="normal",
            scope="session-a",
        )
        later = record(
            db, device, now + timedelta(seconds=2), observation="failure-2", scope="session-a"
        )
        assert generate_guidance(db, device, later)[0].failure_count == 1
        other = record(
            db, device, now + timedelta(seconds=3), observation="failure-3", scope="session-b"
        )
        assert generate_guidance(db, device, other)[0].failure_count == 1


def test_same_diagnosis_episode_upsert_is_idempotent(api_context):
    with api_context["session_factory"]() as db:
        device = db.query(Device).one()
        now = datetime.now(timezone.utc)
        device.last_seen_at = now
        diagnosis = record(db, device, now)
        first = upsert_episode(db, device, diagnosis, [], Settings())
        for _ in range(3):
            same = upsert_episode(db, device, diagnosis, [], Settings())
            assert same.id == first.id
            assert same.failure_count == 1


def test_workflow_history_uses_persisted_session_scope(api_context):
    from uuid import uuid4

    from app.models import DiagnosisWorkflowRun, ExperimentSession

    with api_context["session_factory"]() as db:
        device = db.query(Device).one()
        session = db.query(ExperimentSession).one()
        second_session = ExperimentSession(
            experiment_assignment_id=session.experiment_assignment_id,
            student_user_id=session.student_user_id,
            device_id=device.id,
            status="active",
            started_at=datetime.now(timezone.utc),
            is_test_data=True,
        )
        db.add(second_session)
        db.flush()
        now = datetime.now(timezone.utc)
        device.last_seen_at = now
        episode_ids = []
        for index, owner in enumerate((session, second_session)):
            diagnosis = record(
                db, device, now + timedelta(seconds=index), observation=f"failure-{index}"
            )
            workflow_id = str(uuid4())
            db.add(
                DiagnosisWorkflowRun(
                    id=workflow_id,
                    device_id=device.id,
                    student_user_id=owner.student_user_id,
                    experiment_session_id=owner.id,
                    diagnosis_result_id=diagnosis.id,
                    graph_thread_id=f"diagnosis:{workflow_id}",
                    graph_version="test",
                    status="running",
                )
            )
            db.commit()
            history = generate_guidance(db, device, diagnosis)[0]
            assert history.failure_count == 1
            episode_ids.append(upsert_episode(db, device, diagnosis, [history], Settings()).id)
        assert episode_ids[0] != episode_ids[1]


def test_old_evidence_reentering_window_is_not_a_new_failure(api_context):
    with api_context["session_factory"]() as db:
        device = db.query(Device).one()
        now = datetime.now(timezone.utc)
        device.last_seen_at = now
        for index, (evidence_id, expected) in enumerate(
            [("failure-a", 1), ("failure-b", 2), ("failure-a", 2)]
        ):
            diagnosis = record(db, device, now + timedelta(seconds=index), observation=evidence_id)
            history = generate_guidance(db, device, diagnosis)[0]
            episode = upsert_episode(db, device, diagnosis, [history], Settings())
            assert history.failure_count == episode.failure_count == expected


def test_episode_ownership_survives_new_results_and_resolution(api_context):
    from app.models import DiagnosisEpisode
    from app.services.diagnosis_episode import episode_for_diagnosis, resolve_episode

    with api_context["session_factory"]() as db:
        device = db.query(Device).one()
        now = datetime.now(timezone.utc)
        device.last_seen_at = now
        first = record(db, device, now)
        original = upsert_episode(db, device, first, [], Settings())
        second = record(db, device, now + timedelta(seconds=1), observation="second")
        assert upsert_episode(db, device, second, [], Settings()).id == original.id
        assert original.last_diagnosis_result_id == second.id
        assert episode_for_diagnosis(db, first).id == original.id
        resolve_episode(db, original, "student_resolved")
        third = record(db, device, now + timedelta(seconds=2), observation="third")
        current = upsert_episode(db, device, third, [], Settings())
        assert current.id != original.id
        assert upsert_episode(db, device, first, [], Settings()).id == original.id
        assert original.status == "resolved"
        assert db.query(DiagnosisEpisode).count() == 2
        # Legacy ownership remains unknown even when a historical interval matches.
        first.episode_id = None
        first.episode_evidence_revision = None
        db.commit()
        assert episode_for_diagnosis(db, first) is None
        assert upsert_episode(db, device, first, [], Settings()) is None
        assert first.episode_id is None


def test_first_reasoning_already_has_durable_episode(api_context, monkeypatch):
    from langgraph.checkpoint.memory import InMemorySaver

    import app.ai.diagnosis_graph as graph_module
    from app.diagnosis.workflow_schemas import DiagnosisWorkflowStartRequest
    from app.services.diagnosis_episode import episode_for_diagnosis
    from app.services.diagnosis_workflow import start_workflow

    response = api_context["client"].post(
        "/api/v1/device/logs",
        headers=api_context["headers"],
        json={
            "level": "error",
            "message": "fixture",
            "event_code": "SENSOR_READ_FAILED",
            "occurred_at": datetime.now(timezone.utc).isoformat(),
            "is_test_data": True,
        },
    )
    assert response.status_code == 201
    original = graph_module.reason_about_causes
    checked = []

    def inspect_owner(db, diagnosis, *args, **kwargs):
        assert diagnosis.episode_id is not None
        assert episode_for_diagnosis(db, diagnosis).id == diagnosis.episode_id
        checked.append(diagnosis.id)
        return original(db, diagnosis, *args, **kwargs)

    monkeypatch.setattr(graph_module, "reason_about_causes", inspect_owner)
    with api_context["session_factory"]() as db:
        workflow = start_workflow(
            db,
            graph_module.build_diagnosis_graph(InMemorySaver()),
            db.query(Device).one(),
            Settings(ai_enabled=False),
            DiagnosisWorkflowStartRequest(lookback_seconds=60),
        )
        assert checked == [workflow.diagnosis_result_id]
