import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Optional, Union

from pydantic import ValidationError
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.models.base import utc_now
from app.models.device import Device
from app.models.device_heartbeat import DeviceHeartbeat
from app.models.device_log import DeviceLog
from app.models.ingestion_request import IngestionRequest
from app.models.sensor_reading import SensorReading
from app.schemas.device import (
    DeviceBatchIngestRequest,
    DeviceBatchIngestResponse,
    DeviceBatchRecordResult,
    DeviceHeartbeatCreate,
    DeviceLogCreate,
    SensorReadingCreate,
)


@dataclass(frozen=True)
class ProtocolIngestError(Exception):
    status_code: int
    error_code: str
    message: str
    request_id: str
    details: dict[str, Any]
    retryable: bool = False


def _payload_hash(payload: DeviceBatchIngestRequest) -> str:
    canonical = json.dumps(
        payload.model_dump(mode="json", by_alias=True),
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


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


def ingest_device_batch(
    *,
    db: Session,
    device: Device,
    payload: DeviceBatchIngestRequest,
    expected_protocol_version: str,
    expected_schema_version: str,
    max_records: int,
    requests_per_minute: int,
) -> DeviceBatchIngestResponse:
    request_hash = _payload_hash(payload)
    existing = db.scalar(
        select(IngestionRequest).where(
            IngestionRequest.device_id == device.id,
            IngestionRequest.request_id == payload.request_id,
        )
    )
    if existing is not None:
        if existing.payload_hash != request_hash:
            raise ProtocolIngestError(
                status_code=409,
                error_code="INGESTION_REQUEST_CONFLICT",
                message="requestId was already used with a different payload",
                request_id=payload.request_id,
                details={},
            )
        replay = dict(existing.response_json)
        replay["idempotentReplay"] = True
        return DeviceBatchIngestResponse.model_validate(replay)

    if payload.protocol_version != expected_protocol_version:
        raise ProtocolIngestError(
            status_code=422,
            error_code="UNSUPPORTED_PROTOCOL_VERSION",
            message="protocolVersion is not supported",
            request_id=payload.request_id,
            details={"supported": [expected_protocol_version]},
        )
    if payload.schema_version != expected_schema_version:
        raise ProtocolIngestError(
            status_code=422,
            error_code="UNSUPPORTED_SCHEMA_VERSION",
            message="schemaVersion is not supported",
            request_id=payload.request_id,
            details={"supported": [expected_schema_version]},
        )
    if len(payload.records) > max_records:
        raise ProtocolIngestError(
            status_code=413,
            error_code="INGESTION_BATCH_TOO_LARGE",
            message="record count exceeds the configured batch limit",
            request_id=payload.request_id,
            details={"max_records": max_records, "actual_records": len(payload.records)},
        )

    sequence_owner = db.scalar(
        select(IngestionRequest).where(
            IngestionRequest.device_id == device.id,
            IngestionRequest.boot_id == payload.boot_id,
            IngestionRequest.sequence_no == payload.sequence_no,
        )
    )
    if sequence_owner is not None:
        raise ProtocolIngestError(
            status_code=409,
            error_code="INGESTION_SEQUENCE_CONFLICT",
            message="sequenceNo was already used by another request in this boot",
            request_id=payload.request_id,
            details={"existing_request_id": sequence_owner.request_id},
        )

    server_received_at = utc_now()
    recent_count = db.scalar(
        select(func.count(IngestionRequest.id)).where(
            IngestionRequest.device_id == device.id,
            IngestionRequest.server_received_at >= server_received_at - timedelta(minutes=1),
        )
    )
    if int(recent_count or 0) >= requests_per_minute:
        raise ProtocolIngestError(
            status_code=429,
            error_code="INGESTION_RATE_LIMITED",
            message="device request rate exceeds the configured limit",
            request_id=payload.request_id,
            details={"requests_per_minute": requests_per_minute},
            retryable=True,
        )

    normalized: list[
        tuple[
            str,
            Union[DeviceLogCreate, SensorReadingCreate, DeviceHeartbeatCreate],
            str,
            dict[str, Any],
        ]
    ] = []
    for index, record in enumerate(payload.records):
        try:
            parsed, time_quality = _normalize_protocol_record(
                record_type=record.type,
                occurred_at_raw=record.occurred_at,
                raw_payload=record.payload,
                is_test_data=payload.is_test_data,
                firmware_version=payload.firmware_version,
                server_received_at=server_received_at,
            )
        except ValueError as error:
            raise ProtocolIngestError(
                status_code=422,
                error_code="INGESTION_RECORD_INVALID",
                message="batch record validation failed; no records were stored",
                request_id=payload.request_id,
                details={"record_index": index, "errors": error.args[0]},
            ) from error
        normalized.append((record.type, parsed, time_quality, record.payload))

    max_sequence = db.scalar(
        select(func.max(IngestionRequest.sequence_no)).where(
            IngestionRequest.device_id == device.id,
            IngestionRequest.boot_id == payload.boot_id,
        )
    )
    advances_device_state = max_sequence is None or payload.sequence_no > int(max_sequence)
    sent_at, _ = _parse_device_time(payload.sent_at, server_received_at)
    if payload.sent_at is None:
        sent_at = None

    ingestion = IngestionRequest(
        device_id=device.id,
        request_id=payload.request_id,
        test_run_id=payload.test_run_id,
        protocol_version=payload.protocol_version,
        schema_version=payload.schema_version,
        boot_id=payload.boot_id,
        sequence_no=payload.sequence_no,
        firmware_version=payload.firmware_version,
        sent_at=sent_at,
        uptime_ms=payload.uptime_ms,
        payload_hash=request_hash,
        record_count=len(payload.records),
        response_json={},
        is_test_data=payload.is_test_data,
        server_received_at=server_received_at,
    )
    db.add(ingestion)
    db.flush()

    results: list[DeviceBatchRecordResult] = []
    for index, (record_type, parsed, time_quality, raw_payload) in enumerate(normalized):
        common = {
            "device_id": device.id,
            "ingestion_request_id": ingestion.id,
            "protocol_version": payload.protocol_version,
            "schema_version": payload.schema_version,
            "boot_id": payload.boot_id,
            "sequence_no": payload.sequence_no,
            "uptime_ms": payload.uptime_ms,
            "time_quality": time_quality,
            "raw_payload": raw_payload,
            "is_test_data": payload.is_test_data,
            "received_at": server_received_at,
        }
        if record_type == "log":
            assert isinstance(parsed, DeviceLogCreate)
            stored: Union[DeviceLog, SensorReading, DeviceHeartbeat] = DeviceLog(
                **common,
                level=parsed.level,
                message=parsed.message,
                event_code=parsed.event_code,
                occurred_at=parsed.occurred_at,
                sensor_snapshot=parsed.sensor_snapshot,
            )
        elif record_type == "reading":
            assert isinstance(parsed, SensorReadingCreate)
            stored = SensorReading(
                **common,
                sensor_type=parsed.sensor_type,
                metric_key=parsed.metric_key,
                value=parsed.value,
                unit=parsed.unit,
                observed_at=parsed.observed_at,
                metadata_json=parsed.metadata,
            )
        else:
            assert isinstance(parsed, DeviceHeartbeatCreate)
            stored = DeviceHeartbeat(
                **common,
                observed_at=parsed.observed_at,
                firmware_version=parsed.firmware_version,
                metadata_json=parsed.metadata,
            )
            if advances_device_state:
                device.last_seen_at = server_received_at
                if parsed.firmware_version is not None:
                    device.firmware_version = parsed.firmware_version
        db.add(stored)
        db.flush()
        results.append(
            DeviceBatchRecordResult(
                index=index,
                type=record_type,
                id=stored.id,
                status="accepted",
                timeQuality=time_quality,
            )
        )

    response = DeviceBatchIngestResponse(
        requestId=payload.request_id,
        deviceId=device.device_key,
        acceptedAt=server_received_at,
        idempotentReplay=False,
        retryable=False,
        records=results,
    )
    ingestion.response_json = response.model_dump(mode="json", by_alias=True)
    db.commit()
    return response


def cleanup_test_run(db: Session, device: Device, test_run_id: str) -> dict[str, int]:
    request_ids = list(
        db.scalars(
            select(IngestionRequest.id).where(
                IngestionRequest.device_id == device.id,
                IngestionRequest.test_run_id == test_run_id,
                IngestionRequest.is_test_data.is_(True),
            )
        )
    )
    if not request_ids:
        return {"requests": 0, "logs": 0, "readings": 0, "heartbeats": 0}
    logs = db.execute(
        delete(DeviceLog).where(DeviceLog.ingestion_request_id.in_(request_ids))
    ).rowcount
    readings = db.execute(
        delete(SensorReading).where(SensorReading.ingestion_request_id.in_(request_ids))
    ).rowcount
    heartbeats = db.execute(
        delete(DeviceHeartbeat).where(DeviceHeartbeat.ingestion_request_id.in_(request_ids))
    ).rowcount
    requests = db.execute(
        delete(IngestionRequest).where(IngestionRequest.id.in_(request_ids))
    ).rowcount
    db.commit()
    return {
        "requests": int(requests or 0),
        "logs": int(logs or 0),
        "readings": int(readings or 0),
        "heartbeats": int(heartbeats or 0),
    }


def save_log(db: Session, device: Device, payload: DeviceLogCreate) -> DeviceLog:
    record = DeviceLog(
        device_id=device.id,
        level=payload.level,
        message=payload.message,
        event_code=payload.event_code,
        occurred_at=payload.occurred_at,
        sensor_snapshot=payload.sensor_snapshot,
        raw_payload=payload.model_dump(mode="json"),
        is_test_data=payload.is_test_data,
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return record


def save_reading(db: Session, device: Device, payload: SensorReadingCreate) -> SensorReading:
    record = SensorReading(
        device_id=device.id,
        sensor_type=payload.sensor_type,
        metric_key=payload.metric_key,
        value=payload.value,
        unit=payload.unit,
        observed_at=payload.observed_at,
        metadata_json=payload.metadata,
        raw_payload=payload.model_dump(mode="json"),
        is_test_data=payload.is_test_data,
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return record


def save_heartbeat(db: Session, device: Device, payload: DeviceHeartbeatCreate) -> DeviceHeartbeat:
    received_at = utc_now()
    record = DeviceHeartbeat(
        device_id=device.id,
        observed_at=payload.observed_at,
        firmware_version=payload.firmware_version,
        metadata_json=payload.metadata,
        raw_payload=payload.model_dump(mode="json"),
        is_test_data=payload.is_test_data,
        received_at=received_at,
    )
    device.last_seen_at = received_at
    if payload.firmware_version is not None:
        device.firmware_version = payload.firmware_version
    db.add(record)
    db.commit()
    db.refresh(record)
    return record


def calculate_device_status(
    device: Device, offline_after_seconds: int, now: Optional[datetime] = None
) -> str:
    if device.last_seen_at is None:
        return "never_seen"
    reference = now or datetime.now(timezone.utc)
    last_seen_at = device.last_seen_at
    if last_seen_at.tzinfo is None:
        last_seen_at = last_seen_at.replace(tzinfo=timezone.utc)
    return (
        "online"
        if reference - last_seen_at <= timedelta(seconds=offline_after_seconds)
        else "offline"
    )
