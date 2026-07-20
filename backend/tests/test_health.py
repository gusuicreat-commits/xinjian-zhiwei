from fastapi.testclient import TestClient

from app.main import app


def test_health_check_returns_structured_status() -> None:
    with TestClient(app) as client:
        response = client.get("/api/v1/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "芯鉴知微 API",
        "version": "0.3.0",
        "environment": "development",
    }


def test_openapi_exposes_health_endpoint() -> None:
    with TestClient(app) as client:
        response = client.get("/openapi.json")

    assert response.status_code == 200
    assert "/api/v1/health" in response.json()["paths"]
    assert "/api/v1/device/logs" in response.json()["paths"]
    assert "/api/v1/device/readings" in response.json()["paths"]
    assert "/api/v1/device/heartbeat" in response.json()["paths"]
    assert "/api/v1/device/{device_id}/status" in response.json()["paths"]
