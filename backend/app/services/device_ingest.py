from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy.orm import Session

from app.models.base import utc_now
from app.models.device import Device
from app.models.device_heartbeat import DeviceHeartbeat
from app.models.device_log import DeviceLog
from app.models.sensor_reading import SensorReading
from app.schemas.device import DeviceHeartbeatCreate, DeviceLogCreate, SensorReadingCreate


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
