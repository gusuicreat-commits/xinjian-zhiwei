from datetime import datetime
from typing import Any, Optional

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.base import UuidPrimaryKeyMixin, utc_now


class SensorReading(UuidPrimaryKeyMixin, Base):
    __tablename__ = "sensor_readings"
    __table_args__ = (
        Index("ix_sensor_readings_device_observed", "device_id", "observed_at"),
        Index("ix_sensor_readings_metric_observed", "metric_key", "observed_at"),
    )

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
    sensor_type: Mapped[str] = mapped_column(String(100), nullable=False)
    metric_key: Mapped[str] = mapped_column(String(100), nullable=False)
    value: Mapped[float] = mapped_column(Float, nullable=False)
    unit: Mapped[Optional[str]] = mapped_column(String(50))
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSON, default=dict, nullable=False
    )
    raw_payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    is_test_data: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )

    device = relationship("Device", back_populates="readings")
