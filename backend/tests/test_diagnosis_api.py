from datetime import datetime, timedelta, timezone
from typing import Any

from app.models import DiagnosisResult


def test_diagnosis_builds_context_matches_and_persists(api_context: dict[str, Any]) -> None:
    client = api_context["client"]
    headers = api_context["headers"]
    now = datetime.now(timezone.utc)
    log_response = client.post(
        "/api/v1/device/logs",
        headers=headers,
        json={
            "level": "error",
            "message": "explicit Phase 4 test failure",
            "event_code": "SENSOR_READ_FAILED",
            "occurred_at": now.isoformat(),
            "is_test_data": True,
        },
    )
    reading_response = client.post(
        "/api/v1/device/readings",
        headers=headers,
        json={
            "sensor_type": "generic-test-sensor",
            "metric_key": "generic_metric",
            "value": 11,
            "observed_at": (now - timedelta(seconds=1)).isoformat(),
            "is_test_data": True,
        },
    )
    assert log_response.status_code == 201
    assert reading_response.status_code == 201

    response = client.post(
        "/api/v1/diagnosis/devices/phase2-test-device/run",
        headers=headers,
        json={
            "lookback_seconds": 60,
            "experiment_template": {
                "template_id": "phase4-test-template",
                "metric_ranges": {"generic_metric": {"minimum": 0, "maximum": 10}},
            },
        },
    )

    assert response.status_code == 201
    payload = response.json()
    assert [match["error_type"] for match in payload["matches"]] == [
        "SENSOR_READ_FAILED",
        "DEVICE_OFFLINE",
        "VALUE_OUT_OF_RANGE",
    ]
    assert payload["is_test_data"] is True
    with api_context["session_factory"]() as db:
        record = db.get(DiagnosisResult, payload["id"])
        assert record is not None
        assert len(record.evidence) == 3
        assert record.context_snapshot["experiment_template"]["template_id"] == (
            "phase4-test-template"
        )


def test_diagnosis_rejects_mismatched_authenticated_device(api_context: dict[str, Any]) -> None:
    response = api_context["client"].post(
        "/api/v1/diagnosis/devices/another-device/run",
        headers=api_context["headers"],
        json={},
    )

    assert response.status_code == 401
