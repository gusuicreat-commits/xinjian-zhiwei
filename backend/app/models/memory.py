"""Source relationships and governance only; business records own memory content."""

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, DateTime, ForeignKey, Index, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.base import TimestampMixin, UuidPrimaryKeyMixin, utc_now


class MemoryUse(Base):
    __tablename__ = "memory_uses"
    __table_args__ = (
        Index("ix_memory_use_source", "source_key", "diagnosis_result_id"),
        Index("ix_memory_use_target", "target_type", "target_id"),
        Index("ix_memory_use_diagnosis", "diagnosis_result_id", "id"),
    )
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    source_key: Mapped[str] = mapped_column(String(64), nullable=False)
    source: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    diagnosis_result_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("diagnosis_results.id", ondelete="RESTRICT"), nullable=False
    )
    target_type: Mapped[str] = mapped_column(String(30), nullable=False)
    target_id: Mapped[str] = mapped_column(String(100), nullable=False)
    use_kind: Mapped[str] = mapped_column(String(30), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class MemoryEvent(UuidPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "memory_events"
    __table_args__ = (
        UniqueConstraint("source_key", name="uq_memory_event_source"),
        Index("ix_memory_event_pending", "cache_cleanup_status", "id"),
    )
    source_key: Mapped[str] = mapped_column(String(64), nullable=False)
    source: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    actor_user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    reason: Mapped[str] = mapped_column(String(2000), nullable=False)
    cache_cleanup_status: Mapped[str] = mapped_column(String(30), default="pending", nullable=False)


class MemoryImpactReview(UuidPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "memory_impact_reviews"
    __table_args__ = (
        UniqueConstraint("event_id", "diagnosis_result_id", name="uq_memory_impact_review"),
    )
    event_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("memory_events.id", ondelete="RESTRICT"), nullable=False
    )
    diagnosis_result_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("diagnosis_results.id", ondelete="RESTRICT"), nullable=False
    )
    reviewer_user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    decision: Mapped[str] = mapped_column(String(30), nullable=False)
    note: Mapped[str] = mapped_column(String(2000), nullable=False)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)


class MemoryCleanupPlan(UuidPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "memory_cleanup_plans"
    actor_user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    cutoff: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    targets: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False)
    status: Mapped[str] = mapped_column(String(30), default="planned", nullable=False)
    result: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
