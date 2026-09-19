from datetime import datetime
from typing import Optional

from sqlalchemy import JSON, DateTime, ForeignKey, Index, Integer, String, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.base import TimestampMixin, UuidPrimaryKeyMixin


class DiagnosisEpisode(UuidPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "diagnosis_episodes"
    __table_args__ = (
        Index("ix_diagnosis_episodes_device_status", "device_id", "status"),
        Index("ix_diagnosis_episodes_device_last_seen", "device_id", "last_seen_at"),
        Index(
            "uq_active_problem_scope",
            "scope_key",
            unique=True,
            postgresql_where=text("scope_key IS NOT NULL AND status IN ('open','escalated')"),
            sqlite_where=text("scope_key IS NOT NULL AND status IN ('open','escalated')"),
        ),
    )

    device_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("devices.id", ondelete="CASCADE"), nullable=False
    )
    experiment_id: Mapped[Optional[str]] = mapped_column(String(200))
    primary_error_code: Mapped[str] = mapped_column(String(100), nullable=False)
    scope_key: Mapped[Optional[str]] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(20), default="open", nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    evidence_revision: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0", nullable=False
    )
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
    last_diagnosis_result = relationship("DiagnosisResult", foreign_keys=[last_diagnosis_result_id])
    ai_call_records = relationship("AICallRecord", back_populates="episode")


class DiagnosisIssue(UuidPrimaryKeyMixin, Base):
    """Immutable evidence ownership for each problem in a diagnosis snapshot."""

    __tablename__ = "diagnosis_issues"
    __table_args__ = (
        UniqueConstraint("diagnosis_result_id", "issue_key", name="uq_diagnosis_issue_key"),
    )
    diagnosis_result_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("diagnosis_results.id", ondelete="CASCADE"), index=True
    )
    episode_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("diagnosis_episodes.id", ondelete="RESTRICT"), index=True
    )
    issue_key: Mapped[str] = mapped_column(String(64), nullable=False)
    error_type: Mapped[str] = mapped_column(String(100), nullable=False)
    scope: Mapped[dict] = mapped_column(JSON, nullable=False)
    evidence_keys: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    evidence_revision: Mapped[Optional[int]] = mapped_column(Integer)
    observation_state: Mapped[str] = mapped_column(String(30), default="current", nullable=False)
    episode = relationship("DiagnosisEpisode")
