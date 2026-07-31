from datetime import datetime, timezone
from typing import Any

from app.core.security import hash_password
from app.models import User
from app.services.rbac import assign_role, ensure_rbac_catalog


def _admin_headers(api_context: dict[str, Any]) -> dict[str, str]:
    with api_context["session_factory"]() as db:
        roles = ensure_rbac_catalog(db)
        admin = User(
            username="teacher-dashboard-admin",
            display_name="合成管理员",
            password_hash=hash_password("synthetic-password", iterations=1_000),
            is_test_data=True,
        )
        db.add(admin)
        db.flush()
        assign_role(db, admin, roles["admin"])
        db.commit()
    response = api_context["client"].post(
        "/api/v1/auth/session",
        json={
            "username": "teacher-dashboard-admin",
            "password": "synthetic-password",
        },
    )
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def test_teacher_access_is_protected(api_context: dict[str, Any]) -> None:
    response = api_context["client"].get("/api/v1/teacher/dashboard")
    assert response.status_code == 401


def test_teacher_dashboard_empty_state_does_not_invent_domain_data(
    api_context: dict[str, Any],
) -> None:
    client = api_context["client"]
    headers = _admin_headers(api_context)
    response = client.get("/api/v1/teacher/dashboard", headers=headers)

    assert response.status_code == 200
    payload = response.json()
    assert payload["metrics"]["online_devices"] == 0
    assert payload["metrics"]["never_seen_devices"] == 1
    assert payload["metrics"]["experiment_completion_rate"] is None
    assert payload["class_progress"]["configured"] is False
    assert payload["knowledge_cases"]["configured"] is False
    assert payload["anomalies"] == []


def test_teacher_dashboard_aggregates_ingested_and_diagnosed_test_data(
    api_context: dict[str, Any],
) -> None:
    client = api_context["client"]
    teacher_headers = _admin_headers(api_context)
    device_headers = api_context["headers"]
    now = datetime.now(timezone.utc).isoformat()
    assert (
        client.post(
            "/api/v1/device/heartbeat",
            headers=device_headers,
            json={"observed_at": now, "is_test_data": True},
        ).status_code
        == 201
    )
    assert (
        client.post(
            "/api/v1/device/logs",
            headers=device_headers,
            json={
                "level": "error",
                "message": "Explicit Phase 7 aggregate test",
                "event_code": "SENSOR_READ_FAILED",
                "occurred_at": now,
                "is_test_data": True,
            },
        ).status_code
        == 201
    )
    diagnosis = client.post(
        "/api/v1/diagnosis/devices/phase2-test-device/run",
        headers=device_headers,
        json={"lookback_seconds": 60},
    )
    assert diagnosis.status_code == 201

    response = client.get("/api/v1/teacher/dashboard", headers=teacher_headers)
    assert response.status_code == 200
    payload = response.json()
    assert payload["metrics"]["online_devices"] == 1
    assert payload["metrics"]["abnormal_devices"] == 1
    assert payload["anomalies"][0]["device_id"] == "phase2-test-device"
    assert payload["anomalies"][0]["is_test_data"] is True
    assert payload["error_ranking"][0]["test_data_only"] is True
    assert payload["recent_logs"][0]["event_code"] == "SENSOR_READ_FAILED"
