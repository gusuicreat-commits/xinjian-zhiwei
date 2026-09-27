"""Pure protocol record/time validation shared by ingestion and firmware checks."""

from datetime import datetime, timedelta, timezone
from typing import Any, Optional, Union

from pydantic import ValidationError

from app.schemas.device import DeviceHeartbeatCreate, DeviceLogCreate, SensorReadingCreate


def _parse_device_time(value: Optional[str], server_received_at: datetime) -> tuple[datetime, str]:
    if not value:
        return server_received_at, "server_fallback"
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return server_received_at, "server_fallback"
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return server_received_at, "server_fallback"
    parsed = parsed.astimezone(timezone.utc)
    if parsed.year < 2020 or parsed > server_received_at + timedelta(days=1):
        return server_received_at, "server_fallback"
    return parsed, "device_reported"


def _normalize_protocol_record(
    *,
    record_type: str,
    occurred_at_raw: Optional[str],
    raw_payload: dict[str, Any],
    is_test_data: bool,
    firmware_version: Optional[str],
    server_received_at: datetime,
) -> tuple[Union[DeviceLogCreate, SensorReadingCreate, DeviceHeartbeatCreate], str]:
    values = dict(raw_payload)
    legacy_time = values.pop("occurred_at", None) or values.pop("observed_at", None)
    values.pop("is_test_data", None)
    occurred_at, time_quality = _parse_device_time(
        occurred_at_raw or (str(legacy_time) if legacy_time is not None else None),
        server_received_at,
    )
    try:
        if record_type == "log":
            values["occurred_at"] = occurred_at
            values["is_test_data"] = is_test_data
            return DeviceLogCreate.model_validate(values), time_quality
        if record_type == "reading":
            values["observed_at"] = occurred_at
            values["is_test_data"] = is_test_data
            return SensorReadingCreate.model_validate(values), time_quality
        values["observed_at"] = occurred_at
        values["is_test_data"] = is_test_data
        if firmware_version is not None:
            values["firmware_version"] = firmware_version
        return DeviceHeartbeatCreate.model_validate(values), time_quality
    except ValidationError as error:
        safe_errors = [
            {
                "type": item["type"],
                "location": [str(part) for part in item["loc"]],
                "message": item["msg"],
            }
            for item in error.errors(include_url=False)
        ]
        raise ValueError(safe_errors) from error
