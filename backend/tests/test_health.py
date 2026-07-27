from fastapi.testclient import TestClient

from app.main import app


def test_health_check_returns_structured_status() -> None:
    with TestClient(app) as client:
        response = client.get("/api/v1/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "芯鉴知微 API",
        "version": "1.0.0",
        "environment": "development",
    }


def test_root_probe_paths_are_available() -> None:
    with TestClient(app) as client:
        live = client.get("/health/live")
        openapi = client.get("/openapi.json").json()

    assert live.status_code == 200
    assert live.json()["version"] == "1.0.0"
    assert "/health/ready" in openapi["paths"]
    assert "/health/dependencies" in openapi["paths"]


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
    assert "/api/v1/diagnosis/results/{diagnosis_result_id}/ai-explanation" in response.json()[
        "paths"
    ]
    assert "/api/v1/diagnosis/ai/status" in response.json()["paths"]
    assert "/api/v1/diagnosis/devices/{device_id}/guidance" in response.json()["paths"]
    assert "/api/v1/diagnosis/interventions" in response.json()["paths"]
    assert "/api/v1/student/session" in response.json()["paths"]
    assert "/api/v1/student/dashboard" in response.json()["paths"]
    assert "/api/v1/student/diagnoses/{diagnosis_result_id}/feedback" in response.json()["paths"]
