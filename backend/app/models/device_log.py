from datetime import datetime
from typing import Any, Optional

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.base import UuidPrimaryKeyMixin, utc_now


class DeviceLog(UuidPrimaryKeyMixin, Base):
    __tablename__ = "device_logs"
    __table_args__ = (Index("ix_device_logs_device_occurred", "device_id", "occurred_at"),)

    device_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("devices.id", ondelete="CASCADE"), nullable=False
    )
    ingestion_request_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("ingestion_requests.id", ondelete="SET NULL"), index=True
    )
    protocol_version: Mapped[Optional[str]] = mapped_column(String(20))
    schema_version: Mapped[Optional[str]] = mapped_column(String(20))
    boot_id: Mapped[Optional[str]] = mapped_column(String(100))
    sequence_no: Mapped[Optional[int]] = mapped_column(Integer)
    uptime_ms: Mapped[Optional[int]] = mapped_column(Integer)
    time_quality: Mapped[Optional[str]] = mapped_column(String(30))
    level: Mapped[str] = mapped_column(String(20), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    event_code: Mapped[Optional[str]] = mapped_column(String(100), index=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    sensor_snapshot: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    raw_payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    is_test_data: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )

    device = relationship("Device", back_populates="logs")
