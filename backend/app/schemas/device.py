import math
from datetime import datetime
from typing import Any, Literal, Optional
from uuid import UUID

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


class DeviceProtocolRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    type: Literal["log", "reading", "heartbeat"]
    occurred_at: Optional[str] = Field(
        default=None,
        alias="occurredAt",
        max_length=64,
    )
    payload: dict[str, Any]


class DeviceBatchIngestRequest(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        populate_by_name=True,
        json_schema_extra={
            "examples": [
                {
                    "protocolVersion": "1.0",
                    "schemaVersion": "1",
                    "requestId": "123e4567-e89b-12d3-a456-426614174000",
                    "bootId": "synthetic-boot-id",
                    "sequenceNo": 1,
                    "sentAt": "2026-07-27T08:00:00Z",
                    "uptimeMs": 1000,
                    "firmwareVersion": "synthetic-test-firmware",
                    "isTestData": True,
                    "records": [
                        {
                            "type": "heartbeat",
                            "occurredAt": "2026-07-27T08:00:00Z",
                            "payload": {"metadata": {"source": "synthetic-example"}},
                        }
                    ],
                }
            ]
        },
    )

    protocol_version: str = Field(alias="protocolVersion", min_length=1, max_length=20)
    schema_version: str = Field(alias="schemaVersion", min_length=1, max_length=20)
    request_id: str = Field(alias="requestId", min_length=36, max_length=36)
    test_run_id: Optional[str] = Field(
        default=None,
        alias="testRunId",
        min_length=36,
        max_length=36,
    )
    boot_id: str = Field(alias="bootId", min_length=1, max_length=100)
    sequence_no: int = Field(alias="sequenceNo", ge=0)
    sent_at: Optional[str] = Field(default=None, alias="sentAt", max_length=64)
    uptime_ms: Optional[int] = Field(default=None, alias="uptimeMs", ge=0)
    firmware_version: Optional[str] = Field(
        default=None,
        alias="firmwareVersion",
        max_length=100,
    )
    is_test_data: bool = Field(default=False, alias="isTestData")
    records: list[DeviceProtocolRecord] = Field(min_length=1)

    @field_validator("request_id")
    @classmethod
    def validate_request_id(cls, value: str) -> str:
        try:
            return str(UUID(value))
        except ValueError as error:
            raise ValueError("requestId must be a UUID") from error

    @field_validator("test_run_id")
    @classmethod
    def validate_test_run_id(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        try:
            return str(UUID(value))
        except ValueError as error:
            raise ValueError("testRunId must be a UUID") from error

    def model_post_init(self, __context: Any) -> None:
        if self.test_run_id is not None and not self.is_test_data:
            raise ValueError("testRunId is only allowed when isTestData=true")


class DeviceBatchRecordResult(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    index: int
    type: Literal["log", "reading", "heartbeat"]
    id: str
    status: Literal["accepted"]
    time_quality: Literal["device_reported", "server_fallback"] = Field(alias="timeQuality")


class DeviceBatchIngestResponse(BaseModel):
    model_config = ConfigDict(
        populate_by_name=True,
        json_schema_extra={
            "examples": [
                {
                    "requestId": "123e4567-e89b-12d3-a456-426614174000",
                    "deviceId": "synthetic-device",
                    "acceptedAt": "2026-07-27T08:00:01Z",
                    "idempotentReplay": False,
                    "retryable": False,
                    "records": [
                        {
                            "index": 0,
                            "type": "heartbeat",
                            "id": "stored-record-uuid",
                            "status": "accepted",
                            "timeQuality": "device_reported",
                        }
                    ],
                }
            ]
        },
    )

    request_id: str = Field(alias="requestId")
    device_id: str = Field(alias="deviceId")
    accepted_at: datetime = Field(alias="acceptedAt")
    idempotent_replay: bool = Field(alias="idempotentReplay")
    retryable: bool
    records: list[DeviceBatchRecordResult]


class TestRunCleanupResponse(BaseModel):
    test_run_id: str
    deleted_requests: int
    deleted_logs: int
    deleted_readings: int
    deleted_heartbeats: int
