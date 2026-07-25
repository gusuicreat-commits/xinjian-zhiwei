from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.base import TimestampMixin, UuidPrimaryKeyMixin


class DiagnosisEpisode(UuidPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "diagnosis_episodes"
    __table_args__ = (
        Index("ix_diagnosis_episodes_device_status", "device_id", "status"),
        Index("ix_diagnosis_episodes_device_last_seen", "device_id", "last_seen_at"),
    )

    device_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("devices.id", ondelete="CASCADE"), nullable=False
    )
    experiment_id: Mapped[Optional[str]] = mapped_column(String(200))
    primary_error_code: Mapped[str] = mapped_column(String(100), nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="open", nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    failure_count: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    latest_context_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    current_hint_level: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    last_diagnosis_result_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("diagnosis_results.id", ondelete="CASCADE"), nullable=False
    )
    ai_call_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    resolved_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    resolution_source: Mapped[Optional[str]] = mapped_column(String(100))

    device = relationship("Device")
    last_diagnosis_result = relationship("DiagnosisResult")
    ai_call_records = relationship("AICallRecord", back_populates="episode")
