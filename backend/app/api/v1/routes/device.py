from typing import Annotated

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.api.dependencies import get_authenticated_device
from app.core.config import get_settings
from app.db.session import get_db
from app.models.device import Device
from app.schemas.device import (
    DeviceHeartbeatCreate,
    DeviceLogCreate,
    DeviceStatusResponse,
    IngestResponse,
    SensorReadingCreate,
)
from app.services.device_ingest import (
    calculate_device_status,
    save_heartbeat,
    save_log,
    save_reading,
)

router = APIRouter(prefix="/device", tags=["device"])
AuthenticatedDevice = Annotated[Device, Depends(get_authenticated_device)]
DatabaseSession = Annotated[Session, Depends(get_db)]


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
