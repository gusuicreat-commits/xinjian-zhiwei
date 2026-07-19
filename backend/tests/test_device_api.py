from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.models.device import Device
from app.models.device_heartbeat import DeviceHeartbeat
from app.models.device_log import DeviceLog
from app.models.sensor_reading import SensorReading

TEST_DEVICE_ID = "phase2-test-device"


def test_log_upload_is_authenticated_and_traceable(api_context: dict) -> None:
    payload = {
        "level": "error",
        "message": "Explicit Phase 2 test log",
        "event_code": "TEST_SENSOR_READ_FAILED",
        "occurred_at": "2026-07-19T01:00:00Z",
        "sensor_snapshot": {"metric_a": None},
        "is_test_data": True,
    }
    response = api_context["client"].post(
        "/api/v1/device/logs", json=payload, headers=api_context["headers"]
    )

    assert response.status_code == 201
    assert response.json()["device_id"] == TEST_DEVICE_ID
    with api_context["session_factory"]() as db:
        record = db.scalar(select(DeviceLog))
        assert record is not None
        assert record.message == payload["message"]
        assert record.raw_payload["event_code"] == payload["event_code"]
        assert record.is_test_data is True


def test_sensor_reading_upload_uses_generic_fields(api_context: dict) -> None:
    payload = {
        "sensor_type": "test-sensor-category",
        "metric_key": "test_metric",
        "value": 42.5,
        "unit": "test-unit",
        "observed_at": "2026-07-19T01:01:00Z",
        "metadata": {"channel": "test-channel"},
        "is_test_data": True,
    }
    response = api_context["client"].post(
        "/api/v1/device/readings", json=payload, headers=api_context["headers"]
    )

    assert response.status_code == 201
    with api_context["session_factory"]() as db:
        record = db.scalar(select(SensorReading))
        assert record is not None
        assert record.sensor_type == payload["sensor_type"]
        assert record.metric_key == payload["metric_key"]
        assert record.metadata_json == payload["metadata"]
        assert record.raw_payload["value"] == payload["value"]


def test_heartbeat_updates_last_seen_and_status(api_context: dict) -> None:
    observed_at = datetime.now(timezone.utc).replace(microsecond=0)
    payload = {
        "observed_at": observed_at.isoformat(),
        "firmware_version": "test-firmware",
        "metadata": {"transport": "test"},
        "is_test_data": True,
    }
    response = api_context["client"].post(
        "/api/v1/device/heartbeat", json=payload, headers=api_context["headers"]
    )

    assert response.status_code == 201
    status_response = api_context["client"].get(
        f"/api/v1/device/{TEST_DEVICE_ID}/status",
        headers={"X-Device-Token": api_context["headers"]["X-Device-Token"]},
    )
    assert status_response.status_code == 200
    assert status_response.json()["status"] == "online"
    assert status_response.json()["firmware_version"] == "test-firmware"

    with api_context["session_factory"]() as db:
        device = db.scalar(select(Device))
        heartbeat = db.scalar(select(DeviceHeartbeat))
        assert device is not None and device.last_seen_at is not None
        assert heartbeat is not None
        assert heartbeat.raw_payload["metadata"] == payload["metadata"]


def test_old_heartbeat_reports_offline(api_context: dict) -> None:
    old_time = datetime.now(timezone.utc) - timedelta(minutes=5)
    with api_context["session_factory"]() as db:
        device = db.scalar(select(Device))
        assert device is not None
        device.last_seen_at = old_time
        db.commit()

    status_response = api_context["client"].get(
        f"/api/v1/device/{TEST_DEVICE_ID}/status",
        headers={"X-Device-Token": api_context["headers"]["X-Device-Token"]},
    )
    assert status_response.status_code == 200
    assert status_response.json()["status"] == "offline"


def test_invalid_device_token_is_rejected_without_writing(api_context: dict) -> None:
    headers = {**api_context["headers"], "X-Device-Token": "invalid-token"}
    response = api_context["client"].post(
        "/api/v1/device/logs",
        json={
            "level": "info",
            "message": "Must not be stored",
            "occurred_at": "2026-07-19T01:00:00Z",
            "is_test_data": True,
        },
        headers=headers,
    )

    assert response.status_code == 401
    assert response.json()["detail"]["code"] == "INVALID_DEVICE_TOKEN"
    with api_context["session_factory"]() as db:
        assert db.scalar(select(DeviceLog)) is None


def test_missing_required_payload_field_returns_422(api_context: dict) -> None:
    response = api_context["client"].post(
        "/api/v1/device/readings",
        json={
            "sensor_type": "test-sensor-category",
            "value": 1.0,
            "observed_at": "2026-07-19T01:00:00Z",
            "is_test_data": True,
        },
        headers=api_context["headers"],
    )

    assert response.status_code == 422


def test_timestamp_without_timezone_returns_422(api_context: dict) -> None:
    response = api_context["client"].post(
        "/api/v1/device/heartbeat",
        json={"observed_at": "2026-07-19T01:00:00", "is_test_data": True},
        headers=api_context["headers"],
    )

    assert response.status_code == 422


def test_missing_device_credentials_returns_422(api_context: dict) -> None:
    response = api_context["client"].post(
        "/api/v1/device/heartbeat",
        json={"observed_at": "2026-07-19T01:00:00Z", "is_test_data": True},
    )

    assert response.status_code == 422
