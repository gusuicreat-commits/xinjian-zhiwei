"""Business receipts for deterministic DHT11 queries; no checkpoint dependency."""

from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.base import UuidPrimaryKeyMixin, utc_now


class QueryTask(UuidPrimaryKeyMixin, Base):
    __tablename__ = "query_tasks"
    __table_args__ = (
        UniqueConstraint("session_id", "diagnosis_id", name="uq_query_session_diagnosis"),
        CheckConstraint("query_count >= 0 AND query_count <= 4", name="ck_query_count"),
        CheckConstraint(
            "question_count >= 0 AND question_count <= 1", name="ck_query_question_count"
        ),
    )
    session_id: Mapped[str] = mapped_column(String(36), ForeignKey("experiment_sessions.id"))
    diagnosis_id: Mapped[str] = mapped_column(String(36), ForeignKey("diagnosis_results.id"))
    experiment_version_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("experiment_versions.id")
    )
    contract_version: Mapped[str] = mapped_column(String(40))
    scope_snapshot: Mapped[dict[str, Any]] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(30))
    terminal_reason: Mapped[str | None] = mapped_column(String(40))
    requirements: Mapped[dict[str, Any]] = mapped_column(JSON)
    source_manifest: Mapped[dict[str, Any]] = mapped_column(JSON)
    query_count: Mapped[int] = mapped_column(Integer, default=0)
    question_count: Mapped[int] = mapped_column(Integer, default=0)
    elapsed_ms: Mapped[int] = mapped_column(Integer, default=0)
    is_test_data: Mapped[bool] = mapped_column(Boolean)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class QueryQuestion(UuidPrimaryKeyMixin, Base):
    __tablename__ = "query_questions"
    __table_args__ = (
        UniqueConstraint(
            "task_id", "requirement", "question_id", "version", name="uq_query_question_version"
        ),
        UniqueConstraint("task_id", "requirement", name="uq_query_question_requirement"),
        UniqueConstraint("task_id", "id", name="uq_query_question_owner"),
    )
    task_id: Mapped[str] = mapped_column(String(36), ForeignKey("query_tasks.id"))
    requirement: Mapped[str] = mapped_column(String(50))
    question_id: Mapped[str] = mapped_column(String(100))
    version: Mapped[str] = mapped_column(String(40))
    experiment_version_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("experiment_versions.id")
    )
    status: Mapped[str] = mapped_column(String(20), default="open")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class QueryAnswerReceipt(UuidPrimaryKeyMixin, Base):
    __tablename__ = "query_answer_receipts"
    __table_args__ = (
        ForeignKeyConstraint(
            ["task_id", "question_record_id"], ["query_questions.task_id", "query_questions.id"]
        ),
        UniqueConstraint("task_id", "request_id", name="uq_query_answer_request"),
        UniqueConstraint("question_record_id", name="uq_query_answer_question"),
        CheckConstraint(
            "CAST(value AS TEXT) IN ('matches_table', 'differs', 'unclear')",
            name="ck_query_answer_value",
        ),
    )
    task_id: Mapped[str] = mapped_column(String(36), ForeignKey("query_tasks.id"))
    question_record_id: Mapped[str] = mapped_column(String(36))
    request_id: Mapped[str] = mapped_column(String(36))
    payload_hash: Mapped[str] = mapped_column(String(64))
    value: Mapped[str] = mapped_column(String(20))
    submitted_by_user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"))
    is_test_data: Mapped[bool] = mapped_column(Boolean)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
