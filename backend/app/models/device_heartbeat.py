from datetime import datetime
from typing import Any, Optional

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.base import UuidPrimaryKeyMixin, utc_now


class DeviceHeartbeat(UuidPrimaryKeyMixin, Base):
    __tablename__ = "device_heartbeats"
    __table_args__ = (Index("ix_device_heartbeats_device_observed", "device_id", "observed_at"),)

    device_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("devices.id", ondelete="CASCADE"), nullable=False
    )
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    firmware_version: Mapped[Optional[str]] = mapped_column(String(100))
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSON, default=dict, nullable=False
    )
    raw_payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    is_test_data: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )

    device = relationship("Device", back_populates="heartbeats")
