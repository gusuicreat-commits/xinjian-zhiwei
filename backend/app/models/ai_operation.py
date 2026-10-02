"""Durable logical AI operation; reservations remain the only cost ledger."""

from datetime import datetime

from sqlalchemy import JSON, CheckConstraint, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.base import TimestampMixin, UuidPrimaryKeyMixin


class AIOperation(UuidPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "ai_operations"
    __table_args__ = (
        CheckConstraint(
            "CAST(status AS TEXT) IN ('prepared','dispatching','succeeded',"
            "'failed_known','outcome_unknown')",
            name="ck_ai_operation_status",
        ),
        CheckConstraint("attempt_no >= 0", name="ck_ai_operation_attempt"),
    )

    operation_key: Mapped[str] = mapped_column(String(240), unique=True, nullable=False)
    diagnosis_result_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("diagnosis_results.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    call_stage: Mapped[str] = mapped_column(String(100), nullable=False)
    input_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    execution_versions: Mapped[dict] = mapped_column(JSON, nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    attempt_no: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    deadline_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    retry_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    retry_allowed: Mapped[bool] = mapped_column(default=False, nullable=False)
    error_code: Mapped[str | None] = mapped_column(String(100))
    # Bounded response, already stripped of transport envelope; access is backend only.
    completion: Mapped[dict | None] = mapped_column(JSON)
