from copy import deepcopy
from datetime import datetime, timezone
from typing import Optional
from uuid import uuid4

from sqlalchemy import func, select

from app.models import Device, DeviceHeartbeat, IngestionRequest, SensorReading


def _batch(
    *,
    request_id: Optional[str] = None,
    boot_id: str = "test-boot",
    sequence_no: int = 1,
    firmware_version: str = "synthetic-firmware-v1",
) -> dict[str, object]:
    return {
        "protocolVersion": "1.0",
        "schemaVersion": "1",
        "requestId": request_id or str(uuid4()),
        "bootId": boot_id,
        "sequenceNo": sequence_no,
        "sentAt": "2026-07-27T08:00:00Z",
        "uptimeMs": 1234,
        "firmwareVersion": firmware_version,
        "isTestData": True,
        "records": [
            {
                "type": "heartbeat",
                "occurredAt": "2026-07-27T08:00:00Z",
                "payload": {"metadata": {"source": "protocol-test"}},
            },
            {
                "type": "reading",
                "occurredAt": "2026-07-27T08:00:01Z",
                "payload": {
                    "sensor_type": "generic-test-sensor",
                    "metric_key": "synthetic_metric",
                    "value": 42,
                    "unit": "test-unit",
                    "metadata": {},
                },
            },
            {
                "type": "log",
                "occurredAt": "2026-07-27T08:00:02Z",
                "payload": {
                    "level": "info",
                    "message": "synthetic protocol test log",
                    "event_code": "TEST_PROTOCOL",
                    "sensor_snapshot": {},
                },
            },
        ],
    }


def test_batch_replay_is_idempotent(api_context: dict[str, object]) -> None:
    client = api_context["client"]
    payload = _batch()

    first = client.post("/api/v1/device/ingest", headers=api_context["headers"], json=payload)
    second = client.post("/api/v1/device/ingest", headers=api_context["headers"], json=payload)

    assert first.status_code == 201
    assert second.status_code == 201
    assert first.json()["idempotentReplay"] is False
    assert second.json()["idempotentReplay"] is True
    assert second.json()["records"] == first.json()["records"]

    with api_context["session_factory"]() as db:
        assert db.scalar(select(func.count(IngestionRequest.id))) == 1
        assert db.scalar(select(func.count(DeviceHeartbeat.id))) == 1
        assert db.scalar(select(func.count(SensorReading.id))) == 1


def test_reused_request_id_with_different_payload_is_rejected(
    api_context: dict[str, object],
) -> None:
    client = api_context["client"]
    payload = _batch()
    first = client.post("/api/v1/device/ingest", headers=api_context["headers"], json=payload)
    assert first.status_code == 201
    changed = deepcopy(payload)
    changed["records"][1]["payload"]["value"] = 43

    response = client.post(
        "/api/v1/device/ingest",
        headers=api_context["headers"],
        json=changed,
    )

    assert response.status_code == 409
    assert response.json()["detail"]["error_code"] == "INGESTION_REQUEST_CONFLICT"


def test_same_boot_sequence_with_different_request_is_rejected(
    api_context: dict[str, object],
) -> None:
    client = api_context["client"]
    first = _batch(sequence_no=7)
    second = _batch(sequence_no=7)
    client.post("/api/v1/device/ingest", headers=api_context["headers"], json=first)

    response = client.post(
        "/api/v1/device/ingest",
        headers=api_context["headers"],
        json=second,
    )

    assert response.status_code == 409
    assert response.json()["detail"]["error_code"] == "INGESTION_SEQUENCE_CONFLICT"


def test_out_of_order_batch_preserves_history_without_regressing_device_state(
    api_context: dict[str, object],
) -> None:
    client = api_context["client"]
    newest = _batch(sequence_no=10, firmware_version="synthetic-new")
    older = _batch(sequence_no=9, firmware_version="synthetic-old")

    newest_response = client.post(
        "/api/v1/device/ingest",
        headers=api_context["headers"],
        json=newest,
    )
    assert newest_response.status_code == 201
    with api_context["session_factory"]() as db:
        initial_last_seen = db.scalar(select(Device.last_seen_at))
    assert (
        client.post("/api/v1/device/ingest", headers=api_context["headers"], json=older).status_code
        == 201
    )

    with api_context["session_factory"]() as db:
        device = db.scalar(select(Device))
        assert device is not None
        assert device.firmware_version == "synthetic-new"
        assert device.last_seen_at == initial_last_seen
        assert db.scalar(select(func.count(DeviceHeartbeat.id))) == 2


def test_invalid_device_time_uses_server_time_and_marks_quality(
    api_context: dict[str, object],
) -> None:
    client = api_context["client"]
    payload = _batch()
    payload["records"] = [
        {
            "type": "reading",
            "occurredAt": "not-a-time",
            "payload": {
                "sensor_type": "generic-test-sensor",
                "metric_key": "synthetic_metric",
                "value": 1,
                "metadata": {},
            },
        }
    ]

    response = client.post(
        "/api/v1/device/ingest",
        headers=api_context["headers"],
        json=payload,
    )

    assert response.status_code == 201
    assert response.json()["records"][0]["timeQuality"] == "server_fallback"
    with api_context["session_factory"]() as db:
        reading = db.scalar(select(SensorReading))
        assert reading is not None
        assert reading.time_quality == "server_fallback"
        observed_at = reading.observed_at
        received_at = reading.received_at
        if observed_at.tzinfo is None:
            observed_at = observed_at.replace(tzinfo=timezone.utc)
        if received_at.tzinfo is None:
            received_at = received_at.replace(tzinfo=timezone.utc)
        assert abs((observed_at - received_at).total_seconds()) < 0.01


def test_invalid_record_rejects_entire_batch(api_context: dict[str, object]) -> None:
    client = api_context["client"]
    payload = _batch()
    payload["records"].append(
        {
            "type": "reading",
            "occurredAt": datetime.now(timezone.utc).isoformat(),
            "payload": {"metric_key": "missing_sensor_type", "value": 1},
        }
    )

    response = client.post(
        "/api/v1/device/ingest",
        headers=api_context["headers"],
        json=payload,
    )

    assert response.status_code == 422
    assert response.json()["detail"]["error_code"] == "INGESTION_RECORD_INVALID"
    with api_context["session_factory"]() as db:
        assert db.scalar(select(func.count(IngestionRequest.id))) == 0
        assert db.scalar(select(func.count(DeviceHeartbeat.id))) == 0
        assert db.scalar(select(func.count(SensorReading.id))) == 0


def test_batch_record_limit_returns_stable_error(api_context: dict[str, object]) -> None:
    client = api_context["client"]
    payload = _batch()
    payload["records"] = [
        {
            "type": "heartbeat",
            "occurredAt": "2026-07-27T08:00:00Z",
            "payload": {},
        }
        for _ in range(101)
    ]

    response = client.post(
        "/api/v1/device/ingest",
        headers=api_context["headers"],
        json=payload,
    )

    assert response.status_code == 413
    assert response.json()["detail"]["error_code"] == "INGESTION_BATCH_TOO_LARGE"


def test_synthetic_run_can_be_cleaned_without_touching_other_data(
    api_context: dict[str, object],
) -> None:
    client = api_context["client"]
    test_run_id = str(uuid4())
    targeted = _batch(sequence_no=21)
    targeted["testRunId"] = test_run_id
    retained = _batch(sequence_no=22)

    targeted_response = client.post(
        "/api/v1/device/ingest",
        headers=api_context["headers"],
        json=targeted,
    )
    retained_response = client.post(
        "/api/v1/device/ingest",
        headers=api_context["headers"],
        json=retained,
    )
    assert targeted_response.status_code == 201
    assert retained_response.status_code == 201
    response = client.delete(
        f"/api/v1/device/test-runs/{test_run_id}",
        headers=api_context["headers"],
    )

    assert response.status_code == 200
    assert response.json()["deleted_requests"] == 1
    assert response.json()["deleted_heartbeats"] == 1
    with api_context["session_factory"]() as db:
        assert db.scalar(select(func.count(IngestionRequest.id))) == 1
        assert db.scalar(select(func.count(DeviceHeartbeat.id))) == 1
