from datetime import datetime
from typing import Any, Optional

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.base import TimestampMixin, UuidPrimaryKeyMixin


class DiagnosisWorkflowRun(UuidPrimaryKeyMixin, TimestampMixin, Base):
    """Business audit record for one LangGraph diagnosis workflow.

    LangGraph checkpoints describe how the program is running. This table describes
    what happened in the diagnosis business process and remains queryable even when
    checkpoints are expired or moved to a dedicated database.
    """

    __tablename__ = "diagnosis_workflow_runs"
    __table_args__ = (
        ForeignKeyConstraint(
            ["experiment_version_id", "experiment_record_id"],
            ["experiment_versions.id", "experiment_versions.experiment_id"],
            name="fk_diagnosis_workflow_runs_experiment_version_scope",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "graph_thread_id = 'diagnosis:' || id",
            name="ck_diagnosis_workflow_thread_matches_diagnosis",
        ),
        Index("ix_diagnosis_workflow_device_created", "device_id", "created_at"),
        Index(
            "ix_diagnosis_workflow_session_created",
            "experiment_session_id",
            "created_at",
        ),
        Index("ix_diagnosis_workflow_status_updated", "status", "updated_at"),
    )

    device_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("devices.id", ondelete="CASCADE"), nullable=False
    )
    student_user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    experiment_session_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("experiment_sessions.id", ondelete="RESTRICT"), nullable=False
    )
    experiment_record_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("experiments.id", ondelete="RESTRICT")
    )
    experiment_version_id: Mapped[Optional[str]] = mapped_column(String(36), index=True)
    diagnosis_result_id: Mapped[Optional[str]] = mapped_column(
        String(36),
        ForeignKey("diagnosis_results.id", ondelete="CASCADE"),
        unique=True,
    )
    graph_thread_id: Mapped[str] = mapped_column(String(200), unique=True, nullable=False)
    graph_version: Mapped[str] = mapped_column(String(100), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    current_node: Mapped[Optional[str]] = mapped_column(String(100))
    question: Mapped[Optional[str]] = mapped_column(Text)
    evidence_score: Mapped[Optional[float]] = mapped_column(Float)
    guidance_level: Mapped[Optional[int]] = mapped_column(Integer)
    needs_rag: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    needs_teacher: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    rule_engine_version: Mapped[Optional[str]] = mapped_column(String(100))
    fault_tree_version: Mapped[Optional[str]] = mapped_column(String(100))
    embedding_version: Mapped[Optional[str]] = mapped_column(String(100))
    model_id: Mapped[Optional[str]] = mapped_column(String(200))
    node_trace: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    node_metrics: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list, nullable=False)
    retrieval_audit: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    resume_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    state_revision: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    review_request: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON)
    final_result: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON)
    error_messages: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    is_test_data: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

    device = relationship("Device")
    student = relationship("User", foreign_keys=[student_user_id])
    experiment_session = relationship("ExperimentSession")
    diagnosis_result = relationship("DiagnosisResult")
    reviews = relationship(
        "DiagnosisWorkflowReview",
        back_populates="workflow_run",
        cascade="all, delete-orphan",
    )


class DiagnosisWorkflowReview(UuidPrimaryKeyMixin, Base):
    __tablename__ = "diagnosis_workflow_reviews"
    __table_args__ = (
        Index("ix_diagnosis_workflow_reviews_run_created", "workflow_run_id", "created_at"),
        UniqueConstraint("workflow_run_id", name="uq_diagnosis_workflow_reviews_workflow_run"),
    )

    workflow_run_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("diagnosis_workflow_runs.id", ondelete="CASCADE"),
        nullable=False,
    )
    reviewer_user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    action: Mapped[str] = mapped_column(String(20), nullable=False)
    comment: Mapped[Optional[str]] = mapped_column(Text)
    edited_result: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    workflow_run = relationship("DiagnosisWorkflowRun", back_populates="reviews")
    reviewer = relationship("User")
