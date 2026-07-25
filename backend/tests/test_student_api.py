from datetime import datetime, timezone
from typing import Any

from app.models import DiagnosisFeedback


def test_student_session_and_empty_dashboard_use_real_device_auth(
    api_context: dict[str, Any],
) -> None:
    client = api_context["client"]
    session = client.post("/api/v1/student/session", headers=api_context["headers"])
    dashboard = client.get("/api/v1/student/dashboard", headers=api_context["headers"])

    assert session.status_code == 200
    assert session.json()["auth_mode"] == "device_credential_placeholder"
    assert dashboard.status_code == 200
    payload = dashboard.json()
    assert payload["task"]["configured"] is False
    assert payload["device"]["status"] == "never_seen"
    assert payload["logs"] == []
    assert payload["readings"] == []
    assert payload["diagnosis"] is None
    assert payload["guidance"] == []
    assert payload["ai_status"]["provider_configured"] is False
    assert payload["ai_explanation"] is None


def test_student_dashboard_returns_normal_ingested_data(api_context: dict[str, Any]) -> None:
    client = api_context["client"]
    headers = api_context["headers"]
    now = datetime.now(timezone.utc).isoformat()
    assert (
        client.post(
            "/api/v1/device/heartbeat",
            headers=headers,
            json={"observed_at": now, "is_test_data": True},
        ).status_code
        == 201
    )
    assert (
        client.post(
            "/api/v1/device/readings",
            headers=headers,
            json={
                "sensor_type": "generic-test-sensor",
                "metric_key": "metric_a",
                "value": 5,
                "observed_at": now,
                "is_test_data": True,
            },
        ).status_code
        == 201
    )

    response = client.get("/api/v1/student/dashboard", headers=headers)

    assert response.status_code == 200
    payload = response.json()
    assert payload["device"]["status"] == "online"
    assert payload["readings"][0]["metric_key"] == "metric_a"
    assert payload["diagnosis"] is None


def test_student_dashboard_exposes_diagnosis_guidance_and_feedback(
    api_context: dict[str, Any],
) -> None:
    client = api_context["client"]
    headers = api_context["headers"]
    now = datetime.now(timezone.utc).isoformat()
    assert (
        client.post(
            "/api/v1/device/logs",
            headers=headers,
            json={
                "level": "error",
                "message": "Phase 6 explicit test failure",
                "event_code": "SENSOR_READ_FAILED",
                "occurred_at": now,
                "is_test_data": True,
            },
        ).status_code
        == 201
    )
    diagnosis = client.post(
        "/api/v1/diagnosis/devices/phase2-test-device/run",
        headers=headers,
        json={"lookback_seconds": 60},
    )
    assert diagnosis.status_code == 201
    diagnosis_id = diagnosis.json()["id"]
    guidance = client.post(f"/api/v1/diagnosis/results/{diagnosis_id}/guidance", headers=headers)
    assert guidance.status_code == 201

    feedback = client.post(
        f"/api/v1/student/diagnoses/{diagnosis_id}/feedback",
        headers=headers,
        json={"action": "request_teacher_help", "note": "Phase 6 test feedback"},
    )
    dashboard = client.get("/api/v1/student/dashboard", headers=headers)

    assert feedback.status_code == 201
    assert feedback.json()["is_test_data"] is True
    assert dashboard.status_code == 200
    payload = dashboard.json()
    assert payload["diagnosis"]["id"] == diagnosis_id
    assert len(payload["diagnosis"]["matches"]) == 2
    assert len(payload["guidance"][0]["ranked_causes"]) == 3
    assert payload["feedback"]["action"] == "request_teacher_help"
    with api_context["session_factory"]() as db:
        assert db.query(DiagnosisFeedback).count() == 1


def test_student_feedback_cannot_access_other_diagnosis(api_context: dict[str, Any]) -> None:
    response = api_context["client"].post(
        "/api/v1/student/diagnoses/not-owned/feedback",
        headers=api_context["headers"],
        json={"action": "resolved"},
    )

    assert response.status_code == 404
