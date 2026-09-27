from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from fastapi.routing import APIRoute
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
from app.services.data_scope import ScopeConflict, ScopeViolation, resolve_experiment_session
from app.services.device_ingest import (
    ProtocolIngestError,
    calculate_device_status,
    cleanup_test_run,
    ingest_device_batch,
    ingest_legacy_record,
)


def validated_ingestion_session(
    device: Annotated[Device, Depends(get_authenticated_device)],
    db: Annotated[Session, Depends(get_db)],
    session_id: Annotated[str | None, Header(alias="X-Experiment-Session-ID")] = None,
) -> str | None:
    if session_id is not None:
        try:
            resolve_experiment_session(db, device, session_id, require_active=False)
        except ScopeViolation as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except ScopeConflict as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
    return session_id


IngestionSession = Annotated[str | None, Depends(validated_ingestion_session)]


class BoundedTelemetryRoute(APIRoute):
    def get_route_handler(self):
        handler = super().get_route_handler()

        async def bounded(request: Request):
            if request.method == "POST" and self.path.rsplit("/", 1)[-1] in {
                "ingest",
                "logs",
                "readings",
                "heartbeat",
            }:
                limit = get_settings().device_ingest_max_body_bytes
                chunks, size = [], 0
                async for chunk in request.stream():
                    size += len(chunk)
                    if size > limit:
                        raise HTTPException(
                            status_code=413,
                            detail={
                                "error_code": "INGESTION_BODY_TOO_LARGE",
                                "message": "request body exceeds the configured byte limit",
                                "request_id": None,
                                "details": {"max_bytes": limit},
                                "retryable": False,
                            },
                        )
                    chunks.append(chunk)
                # Cache only bounded bytes before FastAPI parses JSON/Pydantic models.
                request._body = b"".join(chunks)
            return await handler(request)

        return bounded


router = APIRouter(prefix="/device", tags=["device"], route_class=BoundedTelemetryRoute)
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
    session_id: IngestionSession,
) -> DeviceBatchIngestResponse:
    settings = get_settings()
    try:
        return ingest_device_batch(
            db=db,
            device=device,
            payload=payload,
            expected_protocol_version=settings.device_protocol_version,
            expected_schema_version=settings.device_schema_version,
            max_records=settings.device_ingest_max_records,
            experiment_session_id=session_id,
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


def legacy_write(db, device, payload, session_id):
    try:
        return ingest_legacy_record(
            db,
            device,
            payload,
            experiment_session_id=session_id,
            requests_per_minute=get_settings().device_ingest_requests_per_minute,
        )
    except ProtocolIngestError as error:
        raise HTTPException(
            status_code=error.status_code,
            detail={
                "error_code": error.error_code,
                "message": error.message,
                "request_id": None,
                "details": error.details,
                "retryable": error.retryable,
            },
        ) from error


@router.post("/logs", response_model=IngestResponse, status_code=status.HTTP_201_CREATED)
def create_device_log(
    payload: DeviceLogCreate,
    device: AuthenticatedDevice,
    db: DatabaseSession,
    session_id: IngestionSession,
) -> IngestResponse:
    record = legacy_write(db, device, payload, session_id)
    return IngestResponse(id=record.id, device_id=device.device_key, accepted_at=record.received_at)


@router.post("/readings", response_model=IngestResponse, status_code=status.HTTP_201_CREATED)
def create_sensor_reading(
    payload: SensorReadingCreate,
    device: AuthenticatedDevice,
    db: DatabaseSession,
    session_id: IngestionSession,
) -> IngestResponse:
    record = legacy_write(db, device, payload, session_id)
    return IngestResponse(id=record.id, device_id=device.device_key, accepted_at=record.received_at)


@router.post("/heartbeat", response_model=IngestResponse, status_code=status.HTTP_201_CREATED)
def create_device_heartbeat(
    payload: DeviceHeartbeatCreate,
    device: AuthenticatedDevice,
    db: DatabaseSession,
    session_id: IngestionSession,
) -> IngestResponse:
    record = legacy_write(db, device, payload, session_id)
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
