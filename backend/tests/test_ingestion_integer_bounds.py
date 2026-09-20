import pytest
from sqlalchemy import BigInteger, select
from test_device_protocol_v1 import _batch

from app.models import DeviceHeartbeat, DeviceLog, IngestionRequest, SensorReading


@pytest.mark.parametrize("model", [IngestionRequest, DeviceHeartbeat, DeviceLog, SensorReading])
def test_all_persisted_protocol_counters_have_64_bit_storage(model):
    for field in ("sequence_no", "uptime_ms"):
        assert isinstance(model.__table__.c[field].type, BigInteger)


@pytest.mark.parametrize("field", ["sequenceNo", "uptimeMs"])
@pytest.mark.parametrize("value", [-1, 2**53, True, 1.5, "123"])
def test_invalid_integer_batch_is_rejected_without_partial_records(api_context, field, value):
    payload = _batch()
    payload[field] = value
    response = api_context["client"].post(
        "/api/v1/device/ingest", headers=api_context["headers"], json=payload
    )
    assert response.status_code == 422
    with api_context["session_factory"]() as db:
        for model in (IngestionRequest, DeviceHeartbeat, DeviceLog, SensorReading):
            assert list(db.scalars(select(model))) == []


@pytest.mark.parametrize("value", [0, 2**31 - 1, 2**31, 2**32 - 1, 2**53 - 1])
def test_large_values_are_preserved_and_replays_do_not_duplicate(api_context, value):
    payload = _batch(sequence_no=value)
    payload["uptimeMs"] = value
    client = api_context["client"]
    first = client.post("/api/v1/device/ingest", headers=api_context["headers"], json=payload)
    assert first.status_code == 201
    replay = client.post("/api/v1/device/ingest", headers=api_context["headers"], json=payload)
    assert replay.json()["idempotentReplay"] is True
    with api_context["session_factory"]() as db:
        for model in (IngestionRequest, DeviceHeartbeat, DeviceLog, SensorReading):
            row = db.scalars(select(model)).one()
            assert row.sequence_no == row.uptime_ms == value
