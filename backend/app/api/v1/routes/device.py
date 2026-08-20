import json
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.api.dependencies import get_authenticated_device
from app.core.config import get_settings
from app.db.session import get_db
from app.models.device import Device
from app.schemas.device import (
    DeviceBatchIngestRequest,
    DeviceBatchIngestResponse,
    DeviceHeartbeatCreate,
    DeviceLogCreate,
    DeviceStatusResponse,
    IngestResponse,
    SensorReadingCreate,
    TestRunCleanupResponse,
)
from app.services.device_ingest import (
    ProtocolIngestError,
    calculate_device_status,
    cleanup_test_run,
    ingest_device_batch,
    save_heartbeat,
    save_log,
    save_reading,
)

router = APIRouter(prefix="/device", tags=["device"])
AuthenticatedDevice = Annotated[Device, Depends(get_authenticated_device)]
DatabaseSession = Annotated[Session, Depends(get_db)]


@router.post(
    "/ingest",
    response_model=DeviceBatchIngestResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Device Protocol V1 idempotent batch ingestion",
)
def create_device_batch(
    payload: DeviceBatchIngestRequest,
    request: Request,
    device: AuthenticatedDevice,
    db: DatabaseSession,
) -> DeviceBatchIngestResponse:
    settings = get_settings()
    content_length = request.headers.get("content-length")
    declared_size = int(content_length) if content_length and content_length.isdigit() else None
    estimated_size = len(
        json.dumps(
            payload.model_dump(mode="json", by_alias=True),
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
    )
    if (
        declared_size is not None and declared_size > settings.device_ingest_max_body_bytes
    ) or estimated_size > settings.device_ingest_max_body_bytes:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail={
                "error_code": "INGESTION_BODY_TOO_LARGE",
                "message": "request body exceeds the configured byte limit",
                "request_id": payload.request_id,
                "details": {"max_bytes": settings.device_ingest_max_body_bytes},
                "retryable": False,
            },
        )
    try:
        return ingest_device_batch(
            db=db,
            device=device,
            payload=payload,
            expected_protocol_version=settings.device_protocol_version,
            expected_schema_version=settings.device_schema_version,
            max_records=settings.device_ingest_max_records,
            requests_per_minute=settings.device_ingest_requests_per_minute,
        )
    except ProtocolIngestError as error:
        db.rollback()
        raise HTTPException(
            status_code=error.status_code,
            detail={
                "error_code": error.error_code,
                "message": error.message,
                "request_id": error.request_id,
                "details": error.details,
                "retryable": error.retryable,
            },
        ) from error


@router.delete(
    "/test-runs/{test_run_id}",
    response_model=TestRunCleanupResponse,
    summary="Delete only records belonging to one synthetic scenario run",
)
def delete_test_run(
    test_run_id: str,
    device: AuthenticatedDevice,
    db: DatabaseSession,
) -> TestRunCleanupResponse:
    try:
        normalized_id = str(UUID(test_run_id))
    except ValueError as error:
        raise HTTPException(status_code=422, detail="test_run_id must be a UUID") from error
    counts = cleanup_test_run(db, device, normalized_id)
    return TestRunCleanupResponse(
        test_run_id=normalized_id,
        deleted_requests=counts["requests"],
        deleted_logs=counts["logs"],
        deleted_readings=counts["readings"],
        deleted_heartbeats=counts["heartbeats"],
    )


@router.post("/logs", response_model=IngestResponse, status_code=status.HTTP_201_CREATED)
def create_device_log(
    payload: DeviceLogCreate,
    device: AuthenticatedDevice,
    db: DatabaseSession,
) -> IngestResponse:
    record = save_log(db, device, payload)
    return IngestResponse(id=record.id, device_id=device.device_key, accepted_at=record.received_at)


@router.post("/readings", response_model=IngestResponse, status_code=status.HTTP_201_CREATED)
def create_sensor_reading(
    payload: SensorReadingCreate,
    device: AuthenticatedDevice,
    db: DatabaseSession,
) -> IngestResponse:
    record = save_reading(db, device, payload)
    return IngestResponse(id=record.id, device_id=device.device_key, accepted_at=record.received_at)


@router.post("/heartbeat", response_model=IngestResponse, status_code=status.HTTP_201_CREATED)
def create_device_heartbeat(
    payload: DeviceHeartbeatCreate,
    device: AuthenticatedDevice,
    db: DatabaseSession,
) -> IngestResponse:
    record = save_heartbeat(db, device, payload)
    return IngestResponse(id=record.id, device_id=device.device_key, accepted_at=record.received_at)


@router.get("/{device_id}/status", response_model=DeviceStatusResponse)
def get_device_status(
    device: AuthenticatedDevice,
) -> DeviceStatusResponse:
    settings = get_settings()
    return DeviceStatusResponse(
        device_id=device.device_key,
        status=calculate_device_status(device, settings.device_offline_after_seconds),
        last_seen_at=device.last_seen_at,
        firmware_version=device.firmware_version,
        is_active=device.is_active,
    )
