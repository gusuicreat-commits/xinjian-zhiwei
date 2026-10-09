import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Optional, Union

from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.errors import DomainError
from app.models.base import utc_now
from app.models.classroom import ExperimentSession
from app.models.device import Device
from app.models.device_heartbeat import DeviceHeartbeat
from app.models.device_log import DeviceLog
from app.models.ingestion_request import IngestionRequest, LegacyIngestionAdmission
from app.models.sensor_reading import SensorReading
from app.schemas.device import (
    DeviceBatchIngestRequest,
    DeviceBatchIngestResponse,
    DeviceBatchRecordResult,
    DeviceHeartbeatCreate,
    DeviceLogCreate,
    SensorReadingCreate,
)
from app.services.data_scope import (
    ScopeConflict,
    ScopeViolation,
    ingestion_session_id,
    resolve_experiment_session,
)
from app.services.device_protocol import _normalize_protocol_record as _normalize_protocol_record
from app.services.device_protocol import _parse_device_time


@dataclass(frozen=True)
class ProtocolIngestError(DomainError):
    """Explicit device-protocol envelope, mapped by each instance's HTTP status.

    This is not a single retryability category: 401/403/409/413/422 are definitive
    rejections (retryable=False); 429 quota admission is retryable=True after
    backoff with the original request_id and payload. Routes retain this envelope.
    """

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


def lock_ingestion_device(
    db, device, experiment_session_id, request_id="", authenticated_hash=None
):
    authenticated_hash = authenticated_hash if authenticated_hash is not None else device.token_hash
    locked = db.scalar(
        select(Device)
        .where(Device.id == device.id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if locked is None or not locked.is_active or locked.token_hash != authenticated_hash:
        raise ProtocolIngestError(
            401,
            "INVALID_DEVICE_TOKEN",
            "Device credentials are no longer valid",
            request_id,
            {},
        )
    if experiment_session_id is not None:
        # Dependency validation may have happened before waiting for the lock.
        db.scalar(
            select(ExperimentSession)
            .where(ExperimentSession.id == experiment_session_id)
            .execution_options(populate_existing=True)
        )
        try:
            resolve_experiment_session(db, locked, experiment_session_id, require_active=False)
        except (ScopeViolation, ScopeConflict) as exc:
            raise ProtocolIngestError(
                403 if isinstance(exc, ScopeViolation) else 409,
                "INGESTION_SESSION_INVALID",
                str(exc),
                request_id,
                {},
            ) from exc
    return locked


def check_ingestion_quota(db, device, requests_per_minute, request_id=""):
    now = utc_now()
    cutoff = now - timedelta(minutes=1)
    # Receipts already account for batch writes; legacy admissions contain no receipt.
    recent = sum(
        int(
            db.scalar(
                select(func.count(model.id)).where(
                    model.device_id == device.id,
                    timestamp >= cutoff,
                )
            )
            or 0
        )
        for model, timestamp in (
            (IngestionRequest, IngestionRequest.server_received_at),
            (LegacyIngestionAdmission, LegacyIngestionAdmission.received_at),
        )
    )
    if recent >= requests_per_minute:
        raise ProtocolIngestError(
            429,
            "INGESTION_RATE_LIMITED",
            "device request rate exceeds the configured limit",
            request_id,
            {"requests_per_minute": requests_per_minute},
            retryable=True,
        )
    return now


def ingest_device_batch(
    *,
    db: Session,
    device: Device,
    payload: DeviceBatchIngestRequest,
    expected_protocol_version: str,
    expected_schema_version: str,
    max_records: int,
    requests_per_minute: int,
    experiment_session_id: str | None = None,
) -> DeviceBatchIngestResponse:
    """Serialize admission and receipt creation across workers, per device.

    Session commands lock actor then device; ingestion never takes an actor lock.
    No network/model work is performed while the device row is locked.
    """
    authenticated_hash = device.token_hash
    for attempt in range(2):
        try:
            locked = lock_ingestion_device(
                db, device, experiment_session_id, payload.request_id, authenticated_hash
            )
            response = _ingest_device_batch_locked(
                db=db,
                device=locked,
                payload=payload,
                expected_protocol_version=expected_protocol_version,
                expected_schema_version=expected_schema_version,
                max_records=max_records,
                requests_per_minute=requests_per_minute,
                experiment_session_id=experiment_session_id,
            )
            db.commit()  # Also release the lock on an idempotent replay.
            return response
        except IntegrityError as exc:
            db.rollback()
            constraint = getattr(getattr(exc.orig, "diag", None), "constraint_name", None)
            if attempt or constraint not in {
                "uq_ingestion_requests_device_request",
                "uq_ingestion_requests_device_boot_sequence",
            }:
                raise
            # A writer outside this gate raced us: re-lock and inspect the actual
            # committed receipt. Never turn an unrelated integrity error into success.
        except Exception:
            db.rollback()
            raise
    raise AssertionError("unreachable ingestion retry")


def _ingest_device_batch_locked(
    *,
    db: Session,
    device: Device,
    payload: DeviceBatchIngestRequest,
    expected_protocol_version: str,
    expected_schema_version: str,
    max_records: int,
    requests_per_minute: int,
    experiment_session_id: str | None = None,
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

    server_received_at = check_ingestion_quota(db, device, requests_per_minute, payload.request_id)

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
            "experiment_session_id": ingestion_session_id(
                db,
                device,
                parsed.occurred_at if isinstance(parsed, DeviceLogCreate) else parsed.observed_at,
                experiment_session_id,
            ),
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
    return response


def cleanup_test_run(db: Session, device: Device, test_run_id: str) -> dict[str, int]:
    from app.services.source_lifecycle import assert_sources_unused

    device = lock_ingestion_device(db, device, None)
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
    source_ids = set()
    for model in (DeviceLog, SensorReading, DeviceHeartbeat):
        source_ids.update(db.scalars(select(model.id).where(
            model.ingestion_request_id.in_(request_ids)
        )))
    assert_sources_unused(db, device.id, source_ids)
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


def ingest_legacy_record(db, device, payload, *, experiment_session_id, requests_per_minute):
    try:
        locked = lock_ingestion_device(db, device, experiment_session_id)
        now = check_ingestion_quota(db, locked, requests_per_minute)
        db.execute(
            delete(LegacyIngestionAdmission).where(
                LegacyIngestionAdmission.device_id == locked.id,
                LegacyIngestionAdmission.received_at < now - timedelta(minutes=1),
            )
        )
        db.add(LegacyIngestionAdmission(device_id=locked.id, received_at=now))
        save = (
            save_log
            if isinstance(payload, DeviceLogCreate)
            else save_reading
            if isinstance(payload, SensorReadingCreate)
            else save_heartbeat
        )
        return save(db, locked, payload, experiment_session_id=experiment_session_id)
    except Exception:
        db.rollback()
        raise


def save_log(
    db: Session,
    device: Device,
    payload: DeviceLogCreate,
    *,
    experiment_session_id: str | None = None,
) -> DeviceLog:
    record = DeviceLog(
        device_id=device.id,
        experiment_session_id=ingestion_session_id(
            db, device, payload.occurred_at, experiment_session_id
        ),
        level=payload.level,
        message=payload.message,
        event_code=payload.event_code,
        occurred_at=payload.occurred_at,
        sensor_snapshot=payload.sensor_snapshot,
        raw_payload=payload.model_dump(mode="json"),
        time_quality="device_reported",
        is_test_data=payload.is_test_data,
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return record


def save_reading(
    db: Session,
    device: Device,
    payload: SensorReadingCreate,
    *,
    experiment_session_id: str | None = None,
) -> SensorReading:
    record = SensorReading(
        device_id=device.id,
        experiment_session_id=ingestion_session_id(
            db, device, payload.observed_at, experiment_session_id
        ),
        sensor_type=payload.sensor_type,
        metric_key=payload.metric_key,
        value=payload.value,
        unit=payload.unit,
        observed_at=payload.observed_at,
        metadata_json=payload.metadata,
        raw_payload=payload.model_dump(mode="json"),
        time_quality="device_reported",
        is_test_data=payload.is_test_data,
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return record


def save_heartbeat(
    db: Session,
    device: Device,
    payload: DeviceHeartbeatCreate,
    *,
    experiment_session_id: str | None = None,
) -> DeviceHeartbeat:
    received_at = utc_now()
    record = DeviceHeartbeat(
        device_id=device.id,
        experiment_session_id=ingestion_session_id(
            db, device, payload.observed_at, experiment_session_id
        ),
        observed_at=payload.observed_at,
        firmware_version=payload.firmware_version,
        metadata_json=payload.metadata,
        raw_payload=payload.model_dump(mode="json"),
        time_quality="device_reported",
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
