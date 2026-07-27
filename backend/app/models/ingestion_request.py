from datetime import datetime
from typing import Any, Optional

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Index, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.base import TimestampMixin, UuidPrimaryKeyMixin, utc_now


class IngestionRequest(UuidPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "ingestion_requests"
    __table_args__ = (
        UniqueConstraint(
            "device_id",
            "request_id",
            name="uq_ingestion_requests_device_request",
        ),
        UniqueConstraint(
            "device_id",
            "boot_id",
            "sequence_no",
            name="uq_ingestion_requests_device_boot_sequence",
        ),
        Index(
            "ix_ingestion_requests_device_received",
            "device_id",
            "server_received_at",
        ),
        Index("ix_ingestion_requests_test_run", "test_run_id"),
    )

    device_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("devices.id", ondelete="CASCADE"), nullable=False
    )
    request_id: Mapped[str] = mapped_column(String(36), nullable=False)
    test_run_id: Mapped[Optional[str]] = mapped_column(String(36))
    protocol_version: Mapped[str] = mapped_column(String(20), nullable=False)
    schema_version: Mapped[str] = mapped_column(String(20), nullable=False)
    boot_id: Mapped[str] = mapped_column(String(100), nullable=False)
    sequence_no: Mapped[int] = mapped_column(Integer, nullable=False)
    firmware_version: Mapped[Optional[str]] = mapped_column(String(100))
    sent_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    uptime_ms: Mapped[Optional[int]] = mapped_column(Integer)
    payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    record_count: Mapped[int] = mapped_column(Integer, nullable=False)
    response_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    is_test_data: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    server_received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )

    device = relationship("Device", back_populates="ingestion_requests")
