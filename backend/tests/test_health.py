import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import app


@pytest.mark.parametrize("environment", ["development", "test"])
def test_health_check_returns_structured_status(monkeypatch, environment) -> None:
    settings = Settings(_env_file=None, app_env=environment)
    monkeypatch.setattr("app.api.v1.routes.health.get_settings", lambda: settings)
    with TestClient(app) as client:
        response = client.get("/api/v1/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "芯鉴知微 API",
        "version": "1.0.0",
        "environment": environment,
    }


def test_root_probe_paths_are_available() -> None:
    with TestClient(app) as client:
        live = client.get("/health/live")
        openapi = client.get("/openapi.json").json()

    assert live.status_code == 200
    assert live.json()["version"] == "1.0.0"
    assert "/health/ready" in openapi["paths"]
    assert "/health/dependencies" in openapi["paths"]


def test_local_dev_origin_can_preflight_student_session_headers() -> None:
    with TestClient(app) as client:
        response = client.options(
            "/api/v1/student/dashboard",
            headers={
                "Origin": "http://localhost:4173",
                "Access-Control-Request-Method": "GET",
                "Access-Control-Request-Headers": (
                    "X-Device-ID,X-Device-Token,X-Experiment-Session-ID"
                ),
            },
        )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:4173"
    allowed_headers = response.headers["access-control-allow-headers"].lower()
    assert "x-device-id" in allowed_headers
    assert "x-device-token" in allowed_headers
    assert "x-experiment-session-id" in allowed_headers


def test_openapi_exposes_health_endpoint() -> None:
    with TestClient(app) as client:
        response = client.get("/openapi.json")

    assert response.status_code == 200
    assert "/api/v1/health" in response.json()["paths"]
    assert "/api/v1/device/logs" in response.json()["paths"]
    assert "/api/v1/device/readings" in response.json()["paths"]
    assert "/api/v1/device/heartbeat" in response.json()["paths"]
    assert "/api/v1/device/{device_id}/status" in response.json()["paths"]
    assert "/api/v1/diagnosis/devices/{device_id}/run" in response.json()["paths"]
    assert "/api/v1/diagnosis/results/{diagnosis_result_id}/guidance" in response.json()["paths"]
    assert (
        "/api/v1/diagnosis/results/{diagnosis_result_id}/ai-explanation" in response.json()["paths"]
    )
    assert "/api/v1/diagnosis/ai/status" in response.json()["paths"]
    assert "/api/v1/diagnosis/devices/{device_id}/guidance" in response.json()["paths"]
    assert "/api/v1/diagnosis/interventions" in response.json()["paths"]
    assert "/api/v1/student/session" in response.json()["paths"]
    assert "/api/v1/student/dashboard" in response.json()["paths"]
    assert "/api/v1/student/diagnoses/{diagnosis_result_id}/feedback" in response.json()["paths"]


def test_ops_only_counts_current_authorizations_and_pending_work(api_context):
    from datetime import timedelta
    from uuid import uuid4

    from test_episode_lifecycle_r2 import log, run

    from app.api.v1.routes.health import ops_status
    from app.models import AuthSession, InterventionCase, User
    from app.models.base import utc_now

    log(api_context)
    diagnosis = run(api_context)
    with api_context["session_factory"]() as db:
        user = db.query(User).first()
        for expires, revoked in [
            (utc_now() + timedelta(hours=1), None),
            (utc_now() - timedelta(hours=1), None),
            (utc_now() + timedelta(hours=1), utc_now()),
        ]:
            db.add(
                AuthSession(
                    user_id=user.id, token_hash=uuid4().hex, expires_at=expires, revoked_at=revoked
                )
            )
        case = InterventionCase(
            diagnosis_result_id=diagnosis["id"], status="unconfirmed", is_test_data=True
        )
        db.add(case)
        db.commit()
        assert ops_status(None, db).active_sessions == 1
        assert ops_status(None, db).pending_interventions == 1
        case.status = "resolved"
        user.is_active = False
        db.commit()
        result = ops_status(None, db)
        assert result.active_sessions == result.pending_interventions == 0
        assert result.resolved_awaiting_close == 1
