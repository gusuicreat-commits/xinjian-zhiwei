import math
from datetime import datetime
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator


class TraceablePayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    is_test_data: bool = False

    @staticmethod
    def require_timezone(value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("timestamp must include a timezone")
        return value


class DeviceLogCreate(TraceablePayload):
    level: Literal["debug", "info", "warning", "error", "critical"]
    message: str = Field(min_length=1, max_length=4000)
    event_code: Optional[str] = Field(default=None, max_length=100)
    occurred_at: datetime
    sensor_snapshot: dict[str, Any] = Field(default_factory=dict)

    _validate_occurred_at = field_validator("occurred_at")(TraceablePayload.require_timezone)


class SensorReadingCreate(TraceablePayload):
    sensor_type: str = Field(min_length=1, max_length=100)
    metric_key: str = Field(min_length=1, max_length=100)
    value: float
    unit: Optional[str] = Field(default=None, max_length=50)
    observed_at: datetime
    metadata: dict[str, Any] = Field(default_factory=dict)

    _validate_observed_at = field_validator("observed_at")(TraceablePayload.require_timezone)

    @field_validator("value")
    @classmethod
    def require_finite_value(cls, value: float) -> float:
        if not math.isfinite(value):
            raise ValueError("value must be finite")
        return value


class DeviceHeartbeatCreate(TraceablePayload):
    observed_at: datetime
    firmware_version: Optional[str] = Field(default=None, max_length=100)
    metadata: dict[str, Any] = Field(default_factory=dict)

    _validate_observed_at = field_validator("observed_at")(TraceablePayload.require_timezone)


class IngestResponse(BaseModel):
    id: str
    device_id: str
    accepted_at: datetime


class DeviceStatusResponse(BaseModel):
    device_id: str
    status: Literal["online", "offline", "never_seen"]
    last_seen_at: Optional[datetime]
    firmware_version: Optional[str]
    is_active: bool
