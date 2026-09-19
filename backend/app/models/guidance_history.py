from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.base import UuidPrimaryKeyMixin, utc_now


class GuidanceHistory(UuidPrimaryKeyMixin, Base):
    __tablename__ = "guidance_history"
    __table_args__ = (
        UniqueConstraint(
            "diagnosis_result_id",
            "fault_tree_id",
            "episode_id",
            name="uq_guidance_diagnosis_tree_episode",
        ),
        Index(
            "uq_guidance_legacy_tree",
            "diagnosis_result_id",
            "fault_tree_id",
            unique=True,
            postgresql_where=text("episode_id IS NULL"),
            sqlite_where=text("episode_id IS NULL"),
        ),
        Index("ix_guidance_device_created", "device_id", "created_at"),
        Index(
            "ix_guidance_intervention_created",
            "teacher_intervention_required",
            "created_at",
        ),
    )

    device_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("devices.id", ondelete="CASCADE"), nullable=False
    )
    diagnosis_result_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("diagnosis_results.id", ondelete="CASCADE"), nullable=False
    )
    fault_tree_id: Mapped[str] = mapped_column(String(100), nullable=False)
    episode_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("diagnosis_episodes.id", ondelete="RESTRICT"), index=True
    )
    fault_tree_title: Mapped[str] = mapped_column(String(200), nullable=False)
    fault_tree_status: Mapped[str] = mapped_column(String(20), nullable=False)
    fault_tree_version: Mapped[str] = mapped_column(String(100), nullable=False)
    fault_tree_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    fault_tree_source_id: Mapped[str | None] = mapped_column(String(200))
    fault_tree_scope: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    first_detected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    failure_count: Mapped[int] = mapped_column(Integer, nullable=False)
    anomaly_duration_seconds: Mapped[int] = mapped_column(Integer, nullable=False)
    help_wait_seconds: Mapped[int | None] = mapped_column(Integer)
    hint_level: Mapped[int] = mapped_column(Integer, nullable=False)
    teacher_intervention_required: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
    )
    ranked_causes: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list, nullable=False)
    hints: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list, nullable=False)
    is_test_data: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )

    device = relationship("Device", back_populates="guidance_history")
    diagnosis_result = relationship("DiagnosisResult", back_populates="guidance_history")
