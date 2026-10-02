from datetime import datetime
from typing import Optional

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.base import UuidPrimaryKeyMixin, utc_now


class AIUsageReservation(UuidPrimaryKeyMixin, Base):
    """One durable reservation per outbound attempt, including uncertain failures."""

    __tablename__ = "ai_usage_reservations"
    __table_args__ = (
        UniqueConstraint("operation_id", "attempt_no", name="uq_ai_usage_operation_attempt"),
        Index("ix_ai_usage_device_created", "device_id", "created_at"),
        Index("ix_ai_usage_created", "created_at"),
    )

    diagnosis_result_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("diagnosis_results.id", ondelete="CASCADE"), nullable=False
    )
    operation_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("ai_operations.id", ondelete="RESTRICT"), index=True
    )
    attempt_no: Mapped[Optional[int]] = mapped_column(Integer)
    device_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("devices.id", ondelete="CASCADE"), nullable=False
    )
    episode_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("diagnosis_episodes.id", ondelete="SET NULL")
    )
    call_stage: Mapped[str] = mapped_column(String(100), nullable=False)
    provider: Mapped[str] = mapped_column(String(100), nullable=False)
    model: Mapped[str] = mapped_column(String(200), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    reserved_cost: Mapped[Optional[float]] = mapped_column(Float)
    accounted_cost: Mapped[Optional[float]] = mapped_column(Float)
    attribution: Mapped[Optional[dict]] = mapped_column(JSON)
    input_tokens: Mapped[Optional[int]] = mapped_column(Integer)
    output_tokens: Mapped[Optional[int]] = mapped_column(Integer)
    error_code: Mapped[Optional[str]] = mapped_column(String(100))
    is_test_data: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
