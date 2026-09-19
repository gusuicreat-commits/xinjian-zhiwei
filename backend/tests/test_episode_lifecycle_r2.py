from datetime import datetime, timezone
from uuid import uuid4

from app.models import DiagnosisEpisode, DiagnosisResult, GuidanceHistory


def log(ctx, occurred_at=None):
    response = ctx["client"].post(
        "/api/v1/device/logs",
        headers=ctx["headers"],
        json={
            "level": "error",
            "message": "synthetic failure",
            "event_code": "SENSOR_READ_FAILED",
            "occurred_at": (occurred_at or datetime.now(timezone.utc)).isoformat(),
            "is_test_data": True,
        },
    )
    assert response.status_code == 201


def run(ctx, **extra):
    response = ctx["client"].post(
        "/api/v1/diagnosis/devices/phase2-test-device/run",
        headers=ctx["headers"],
        json={"lookback_seconds": 60, **extra},
    )
    assert response.status_code == 201, response.text
    return response.json()


def feedback(ctx, result, action, request_id=None):
    return ctx["client"].post(
        f"/api/v1/student/diagnoses/{result['id']}/feedback",
        headers=ctx["headers"],
        json={"request_id": request_id or str(uuid4()), "action": action},
    )


def test_old_result_without_new_evidence_can_resolve_and_replay_stays_closed(api_context):
    log(api_context)
    first, second = run(api_context), run(api_context)
    request_id = str(uuid4())
    assert feedback(api_context, first, "resolved", request_id).status_code == 201
    assert feedback(api_context, first, "resolved", request_id).status_code == 201
    repeated = run(api_context)
    assert repeated["episode"]["id"] == first["episode"]["id"] == second["episode"]["id"]
    assert repeated["episode"]["status"] == "resolved"
    with api_context["session_factory"]() as db:
        assert db.query(DiagnosisEpisode).count() == 1


def test_stale_resolution_conflicts_but_teacher_help_applies(api_context):
    log(api_context)
    first = run(api_context)
    log(api_context)
    second = run(api_context)
    assert feedback(api_context, first, "resolved").status_code == 409
    assert feedback(api_context, first, "request_teacher_help").status_code == 201
    with api_context["session_factory"]() as db:
        episode = db.get(DiagnosisEpisode, second["episode"]["id"])
        assert episode.status == "escalated"
        assert episode.current_hint_level == 4


def test_new_failure_after_resolved_starts_new_tree_baseline(api_context):
    for _ in range(3):
        log(api_context)
        previous = run(api_context)
    assert previous["episode"]["failure_count"] == 3
    assert feedback(api_context, previous, "resolved").status_code == 201
    log(api_context)
    current = run(api_context)
    assert current["episode"]["id"] != previous["episode"]["id"]
    assert current["episode"]["failure_count"] == 1
    with api_context["session_factory"]() as db:
        guidance = db.query(GuidanceHistory).filter_by(diagnosis_result_id=current["id"]).one()
        assert guidance.failure_count == guidance.hint_level == 1
        assert guidance.anomaly_duration_seconds == 0


def test_unrelated_rule_evidence_does_not_increment_sensor_tree(api_context):
    log(api_context)
    template = {
        "template_id": "r2",
        "metric_ranges": {"temperature": {"minimum": 0, "maximum": 50}},
    }
    for index in range(3):
        if index:
            response = api_context["client"].post(
                "/api/v1/device/readings",
                headers=api_context["headers"],
                json={
                    "sensor_type": "synthetic",
                    "metric_key": "temperature",
                    "value": 99,
                    "observed_at": datetime.now(timezone.utc).isoformat(),
                    "is_test_data": True,
                },
            )
            assert response.status_code == 201
        result = run(api_context, experiment_template=template)
        if index == 0:
            original_sensor_diagnosis = result
        with api_context["session_factory"]() as db:
            guidance = db.query(GuidanceHistory).filter_by(diagnosis_result_id=result["id"]).one()
            assert guidance.failure_count == guidance.hint_level == 1
            diagnosis = db.get(DiagnosisResult, result["id"])
            assert diagnosis.episode_evidence_revision == 1
    # Unrelated temperature evidence must not stale the sensor episode's feedback.
    assert feedback(api_context, original_sensor_diagnosis, "resolved").status_code == 201


def test_feedback_rejects_conflicting_snapshot_and_workflow_owners(api_context):
    from app.models import DiagnosisFeedback, DiagnosisWorkflowRun, ExperimentSession

    log(api_context)
    result = run(api_context)
    with api_context["session_factory"]() as db:
        diagnosis = db.get(DiagnosisResult, result["id"])
        owner = db.get(ExperimentSession, api_context["experiment_session_id"])
        workflow_id = str(uuid4())
        db.add(
            DiagnosisWorkflowRun(
                id=workflow_id,
                device_id=diagnosis.device_id,
                student_user_id=owner.student_user_id,
                experiment_session_id=owner.id,
                diagnosis_result_id=diagnosis.id,
                graph_thread_id=f"diagnosis:{workflow_id}",
                graph_version="test",
                status="completed",
            )
        )
        diagnosis.context_snapshot = {
            **diagnosis.context_snapshot,
            "feedback_scope": {
                **diagnosis.context_snapshot["feedback_scope"],
                "student_user_id": "conflicting-owner",
            },
        }
        db.commit()
    response = feedback(api_context, result, "resolved")
    assert response.status_code == 403
    with api_context["session_factory"]() as db:
        assert db.query(DiagnosisFeedback).count() == 0
        assert db.get(DiagnosisEpisode, result["episode"]["id"]).status == "open"


def test_latest_sliding_window_can_resolve_after_old_evidence_expires(api_context):
    from datetime import timedelta

    log(api_context, occurred_at=datetime.now(timezone.utc) - timedelta(seconds=30))
    first = run(api_context)
    # The later window excludes the old source without rewriting source data or
    # its earlier immutable diagnosis snapshot.
    log(api_context)
    latest = run(api_context, lookback_seconds=10)
    with api_context["session_factory"]() as db:
        previous = db.get(DiagnosisResult, first["id"])
        current = db.get(DiagnosisResult, latest["id"])
        assert previous.episode_id == current.episode_id
        assert current.episode_evidence_revision == 2
    assert feedback(api_context, latest, "resolved").status_code == 201
    with api_context["session_factory"]() as db:
        assert db.get(DiagnosisEpisode, latest["episode"]["id"]).status == "resolved"


def test_unbound_historical_feedback_does_not_guess_or_write_ownership(api_context):

    log(api_context)
    result = run(api_context)
    with api_context["session_factory"]() as db:
        diagnosis = db.get(DiagnosisResult, result["id"])
        diagnosis.episode_id = None
        diagnosis.episode_evidence_revision = None
        db.commit()
    for action in ("resolved", "request_teacher_help", "unresolved"):
        response = feedback(api_context, result, action)
        assert response.status_code == 409
        assert "no recorded episode ownership" in response.json()["detail"]
    with api_context["session_factory"]() as db:
        from app.models import DiagnosisFeedback

        diagnosis = db.get(DiagnosisResult, result["id"])
        assert diagnosis.episode_id is None
        assert diagnosis.episode_evidence_revision is None
        assert db.query(DiagnosisFeedback).count() == 0


def test_new_diagnosis_without_anomaly_keeps_feedback_compatible(api_context):
    response = api_context["client"].post(
        "/api/v1/device/heartbeat",
        headers=api_context["headers"],
        json={"observed_at": datetime.now(timezone.utc).isoformat(), "is_test_data": True},
    )
    assert response.status_code == 201
    result = run(api_context)
    assert result["matches"] == []
    assert result["episode"] is None
    assert feedback(api_context, result, "resolved").status_code == 201
