"""Durable identity and immutable input for an explicit student check."""

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, DateTime, ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.base import UuidPrimaryKeyMixin, utc_now


class DiagnosisCheck(UuidPrimaryKeyMixin, Base):
    __tablename__ = "diagnosis_checks"
    __table_args__ = (
        UniqueConstraint("session_id", "request_id", name="uq_check_session_request"),
        Index("ix_diagnosis_checks_session_created", "session_id", "created_at"),
    )
    session_id: Mapped[str] = mapped_column(String(36), ForeignKey("experiment_sessions.id"))
    student_user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"))
    device_id: Mapped[str] = mapped_column(String(36), ForeignKey("devices.id"))
    request_id: Mapped[str] = mapped_column(String(36))
    request_payload: Mapped[dict[str, Any]] = mapped_column(JSON)
    payload_hash: Mapped[str] = mapped_column(String(64))
    baseline_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("diagnosis_results.id"))
    workflow_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("diagnosis_workflow_runs.id")
    )
    status: Mapped[str] = mapped_column(String(30), default="pending")
    input_signature: Mapped[str] = mapped_column(String(64))
    context_snapshot: Mapped[dict[str, Any]] = mapped_column(JSON)
    result: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
