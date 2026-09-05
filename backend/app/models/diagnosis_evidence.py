from datetime import datetime
from typing import Any, Optional

from sqlalchemy import (
    JSON,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.base import UuidPrimaryKeyMixin, utc_now


class DiagnosisEvidence(UuidPrimaryKeyMixin, Base):
    """Normalized evidence with a traceable link to its original device fact."""

    __tablename__ = "diagnosis_evidence"
    __table_args__ = (
        ForeignKeyConstraint(
            ["experiment_version_id", "experiment_record_id"],
            ["experiment_versions.id", "experiment_versions.experiment_id"],
            name="fk_diagnosis_evidence_experiment_version_scope",
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "diagnosis_id",
            "evidence_type",
            "source_type",
            "source_ref",
            name="uq_diagnosis_evidence_source",
        ),
        Index("ix_diagnosis_evidence_diagnosis_time", "diagnosis_id", "occurred_at"),
        Index(
            "ix_diagnosis_evidence_experiment_type",
            "experiment_record_id",
            "evidence_type",
        ),
    )

    diagnosis_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("diagnosis_results.id", ondelete="CASCADE"), nullable=False
    )
    experiment_record_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("experiments.id", ondelete="RESTRICT")
    )
    experiment_version_id: Mapped[Optional[str]] = mapped_column(String(36))
    evidence_type: Mapped[str] = mapped_column(String(100), nullable=False)
    source_type: Mapped[str] = mapped_column(String(50), nullable=False)
    source_ref: Mapped[str] = mapped_column(String(200), nullable=False)
    normalized_value: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    raw_payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
