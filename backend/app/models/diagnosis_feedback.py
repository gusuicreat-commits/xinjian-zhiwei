from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.base import UuidPrimaryKeyMixin, utc_now


class DiagnosisFeedback(UuidPrimaryKeyMixin, Base):
    __tablename__ = "diagnosis_feedback"
    __table_args__ = (
        Index("ix_feedback_device_created", "device_id", "created_at"),
        UniqueConstraint("diagnosis_result_id", "request_id", name="uq_feedback_diagnosis_request"),
    )

    # Nullable only for immutable records created before request-scoped feedback.
    request_id: Mapped[Optional[str]] = mapped_column(String(36))
    experiment_session_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("experiment_sessions.id", ondelete="RESTRICT")
    )
    processing_status: Mapped[Optional[str]] = mapped_column(String(20))

    device_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("devices.id", ondelete="CASCADE"), nullable=False
    )
    diagnosis_result_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("diagnosis_results.id", ondelete="CASCADE"), nullable=False
    )
    action: Mapped[str] = mapped_column(String(30), nullable=False)
    note: Mapped[Optional[str]] = mapped_column(Text)
    is_test_data: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )

    device = relationship("Device", back_populates="diagnosis_feedback")
    diagnosis_result = relationship("DiagnosisResult", back_populates="feedback")
