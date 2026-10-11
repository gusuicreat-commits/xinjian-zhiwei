"""Device Protocol V1 payload construction."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional
from uuid import uuid4

FIRMWARE_VERSION = "esp32s3-sht31-1.0.0"
PROTOCOL_VERSION = "1.0"
SCHEMA_VERSION = "1"


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso_millis(value: datetime) -> str:
    value = value.astimezone(timezone.utc)
    return value.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _evidence_metadata(time_source: str) -> dict[str, str]:
    return {"time_source": time_source, "source": "serial_bridge"}


def record_for_line(
    parsed: Any, *, received_at: Optional[datetime], replay: bool
) -> list[dict[str, Any]]:
    """Convert one parsed line to protocol records."""
    time_source = "replay_unknown" if replay else "host_serial_receive"
    occurred_at = None if replay or received_at is None else iso_millis(received_at)
    metadata = _evidence_metadata(time_source)
    if parsed.kind == "reading":
        common = {"occurredAt": occurred_at} if occurred_at else {}
        return [
            {
                "type": "reading",
                **common,
                "payload": {
                    "sensor_type": "SHT31",
                    "metric_key": "temperature",
                    "value": parsed.temperature,
                    "unit": "°C",
                    "metadata": metadata,
                },
            },
            {
                "type": "reading",
                **common,
                "payload": {
                    "sensor_type": "SHT31",
                    "metric_key": "humidity",
                    "value": parsed.humidity,
                    "unit": "%RH",
                    "metadata": metadata,
                },
            },
        ]
    if parsed.kind == "failure":
        common = {"occurredAt": occurred_at} if occurred_at else {}
        return [
            {
                "type": "log",
                **common,
                "payload": {
                    "level": "error",
                    "event_code": "SHT31_READ_FAILED",
                    "message": parsed.text,
                    "sensor_snapshot": metadata,
                },
            }
        ]
    if parsed.kind == "boot":
        common = {"occurredAt": occurred_at} if occurred_at else {}
        return [
            {
                "type": "log",
                **common,
                "payload": {
                    "level": "info",
                    "event_code": "SHT31_BOOT",
                    "message": parsed.text,
                    "sensor_snapshot": metadata,
                },
            }
        ]
    raise ValueError(f"unsupported parsed line kind: {parsed.kind}")


def heartbeat_record(*, received_at: Optional[datetime], replay: bool) -> dict[str, Any]:
    time_source = "replay_unknown" if replay else "host_serial_receive"
    result: dict[str, Any] = {
        "type": "heartbeat",
        "payload": {"metadata": _evidence_metadata(time_source)},
    }
    if not replay and received_at is not None:
        result["occurredAt"] = iso_millis(received_at)
    return result


def make_batch(
    records: list[dict[str, Any]],
    *,
    boot_id: str,
    sequence_no: int,
    firmware_version: str,
    is_test_data: bool,
) -> dict[str, Any]:
    return {
        "protocolVersion": PROTOCOL_VERSION,
        "schemaVersion": SCHEMA_VERSION,
        "requestId": str(uuid4()),
        "bootId": boot_id,
        "sequenceNo": sequence_no,
        "firmwareVersion": firmware_version,
        "isTestData": is_test_data,
        "records": records,
    }
