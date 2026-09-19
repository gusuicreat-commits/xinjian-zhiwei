from typing import Any

from app.api.dependencies import require_review_access
from app.main import app
from app.models import GuidanceHistory


def create_sensor_failure_diagnosis(api_context: dict[str, Any]) -> dict[str, Any]:
    client = api_context["client"]
    headers = api_context["headers"]
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc)
    assert (
        client.post(
            "/api/v1/device/logs",
            headers=headers,
            json={
                "level": "error",
                "message": "Phase 5 test failure",
                "event_code": "SENSOR_READ_FAILED",
                "occurred_at": now.isoformat(),
                "is_test_data": True,
            },
        ).status_code
        == 201
    )
    response = client.post(
        "/api/v1/diagnosis/devices/phase2-test-device/run",
        headers=headers,
        json={"lookback_seconds": 60},
    )
    assert response.status_code == 201
    return response.json()


def test_guidance_api_persists_ranked_reasons_and_is_idempotent(
    api_context: dict[str, Any],
) -> None:
    diagnosis_payload = create_sensor_failure_diagnosis(api_context)
    path = f"/api/v1/diagnosis/results/{diagnosis_payload['id']}/guidance"

    first = api_context["client"].post(path, headers=api_context["headers"])
    second = api_context["client"].post(path, headers=api_context["headers"])

    assert first.status_code == 201
    assert second.status_code == 201
    assert first.json() == second.json()
    item = first.json()["items"][0]
    assert item["hint_level"] == 1
    assert len(item["ranked_causes"]) == 3
    assert all(cause["confidence"] == "low" for cause in item["ranked_causes"])
    with api_context["session_factory"]() as db:
        assert db.query(GuidanceHistory).count() == 1


def test_repeated_failures_escalate_and_appear_in_intervention_list(
    api_context: dict[str, Any],
) -> None:
    # Each iteration contributes a new persisted failed observation.
    for _ in range(10):
        diagnosis_payload = create_sensor_failure_diagnosis(api_context)
    with api_context["session_factory"]() as db:
        last = (
            db.query(GuidanceHistory).filter_by(diagnosis_result_id=diagnosis_payload["id"]).one()
        )
        assert last.failure_count == 10
        assert last.hint_level == 4
        assert last.teacher_intervention_required is True

    app.dependency_overrides[require_review_access] = lambda: None
    try:
        response = api_context["client"].get("/api/v1/diagnosis/interventions")
    finally:
        app.dependency_overrides.pop(require_review_access, None)

    assert response.status_code == 200
    assert response.json()[0]["device_id"] == "phase2-test-device"
    assert response.json()[0]["hint_level"] == 4


def test_intervention_list_fails_closed_without_configuration(
    api_context: dict[str, Any],
) -> None:
    response = api_context["client"].get("/api/v1/diagnosis/interventions")

    assert response.status_code == 503


def test_rerunning_same_telemetry_does_not_escalate(api_context):
    create_sensor_failure_diagnosis(api_context)
    for _ in range(10):
        response = api_context["client"].post(
            "/api/v1/diagnosis/devices/phase2-test-device/run",
            headers=api_context["headers"],
            json={"lookback_seconds": 60},
        )
        assert response.status_code == 201
        result = response.json()
        assert result["episode"]["failure_count"] == 1
        assert result["episode"]["current_hint_level"] == 1
        with api_context["session_factory"]() as db:
            guidance = db.query(GuidanceHistory).filter_by(diagnosis_result_id=result["id"]).one()
            assert guidance.failure_count == 1
            assert guidance.hint_level == 1
