from datetime import datetime
from typing import Any, Optional

from sqlalchemy import JSON, Boolean, DateTime, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.base import TimestampMixin, UuidPrimaryKeyMixin


class Device(UuidPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "devices"

    device_key: Mapped[str] = mapped_column(String(128), unique=True, index=True, nullable=False)
    display_name: Mapped[Optional[str]] = mapped_column(String(200))
    device_type: Mapped[Optional[str]] = mapped_column(String(100))
    hardware_model: Mapped[Optional[str]] = mapped_column(String(200))
    token_hash: Mapped[str] = mapped_column(String(512), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    last_seen_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), index=True)
    firmware_version: Mapped[Optional[str]] = mapped_column(String(100))
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSON, default=dict, nullable=False
    )

    logs = relationship("DeviceLog", back_populates="device", cascade="all, delete-orphan")
    readings = relationship("SensorReading", back_populates="device", cascade="all, delete-orphan")
    heartbeats = relationship(
        "DeviceHeartbeat", back_populates="device", cascade="all, delete-orphan"
    )
    diagnosis_results = relationship(
        "DiagnosisResult", back_populates="device", cascade="all, delete-orphan"
    )
    guidance_history = relationship(
        "GuidanceHistory", back_populates="device", cascade="all, delete-orphan"
    )
    diagnosis_feedback = relationship(
        "DiagnosisFeedback", back_populates="device", cascade="all, delete-orphan"
    )
