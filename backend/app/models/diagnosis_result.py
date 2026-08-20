from datetime import datetime
from typing import Any, Optional

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.base import UuidPrimaryKeyMixin, utc_now


class DiagnosisResult(UuidPrimaryKeyMixin, Base):
    __tablename__ = "diagnosis_results"
    __table_args__ = (Index("ix_diagnosis_results_device_created", "device_id", "created_at"),)

    device_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("devices.id", ondelete="CASCADE"), nullable=False
    )
    evaluated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ruleset_version: Mapped[str] = mapped_column(String(100), nullable=False)
    ruleset_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    input_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    matched_rules: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list, nullable=False)
    evidence: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list, nullable=False)
    context_snapshot: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    experiment_id: Mapped[Optional[str]] = mapped_column(String(100), index=True)
    experiment_version: Mapped[Optional[str]] = mapped_column(String(50))
    experiment_definition_hash: Mapped[Optional[str]] = mapped_column(String(64))
    knowledge_scope: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON)
    deterministic_core: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON)
    deterministic_explanation: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON)
    ai_enhancement: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON)
    is_test_data: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )

    device = relationship("Device", back_populates="diagnosis_results")
    guidance_history = relationship(
        "GuidanceHistory", back_populates="diagnosis_result", cascade="all, delete-orphan"
    )
    feedback = relationship(
        "DiagnosisFeedback", back_populates="diagnosis_result", cascade="all, delete-orphan"
    )
    ai_call_records = relationship(
        "AICallRecord", back_populates="diagnosis_result", cascade="all, delete-orphan"
    )
