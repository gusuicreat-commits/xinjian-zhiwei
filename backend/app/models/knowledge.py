from datetime import datetime
from typing import Any, Optional

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.base import TimestampMixin, UuidPrimaryKeyMixin, utc_now


class KnowledgeSource(UuidPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "knowledge_sources"

    source_key: Mapped[str] = mapped_column(String(128), unique=True, index=True, nullable=False)
    source_type: Mapped[str] = mapped_column(String(50), index=True, nullable=False)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    source_uri: Mapped[Optional[str]] = mapped_column(String(1000))
    version: Mapped[Optional[str]] = mapped_column(String(100))
    license_name: Mapped[Optional[str]] = mapped_column(String(200))
    authorization_scope: Mapped[Optional[str]] = mapped_column(Text)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    is_test_data: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    documents = relationship(
        "KnowledgeDocument", back_populates="source", cascade="all, delete-orphan"
    )


class KnowledgeDocument(UuidPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "knowledge_documents"
    __table_args__ = (
        UniqueConstraint("source_id", "content_hash", name="uq_knowledge_document_source_hash"),
        Index("ix_knowledge_documents_review_created", "review_status", "created_at"),
    )

    source_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("knowledge_sources.id", ondelete="CASCADE"), nullable=False
    )
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    media_type: Mapped[str] = mapped_column(String(100), nullable=False)
    language: Mapped[Optional[str]] = mapped_column(String(30))
    storage_uri: Mapped[Optional[str]] = mapped_column(String(1000))
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    parser_name: Mapped[str] = mapped_column(String(100), nullable=False)
    parser_version: Mapped[str] = mapped_column(String(50), nullable=False)
    review_status: Mapped[str] = mapped_column(
        String(20), default="pending", index=True, nullable=False
    )
    is_test_data: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    source = relationship("KnowledgeSource", back_populates="documents")
    chunks = relationship("KnowledgeChunk", back_populates="document", cascade="all, delete-orphan")
    reviews = relationship(
        "KnowledgeReview", back_populates="document", cascade="all, delete-orphan"
    )


class KnowledgeChunk(UuidPrimaryKeyMixin, Base):
    __tablename__ = "knowledge_chunks"
    __table_args__ = (
        UniqueConstraint("document_id", "chunk_index", name="uq_knowledge_chunk_position"),
        Index("ix_knowledge_chunks_review_document", "review_status", "document_id"),
    )

    document_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("knowledge_documents.id", ondelete="CASCADE"), nullable=False
    )
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    char_count: Mapped[int] = mapped_column(Integer, nullable=False)
    locator_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    review_status: Mapped[str] = mapped_column(
        String(20), default="pending", index=True, nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )

    document = relationship("KnowledgeDocument", back_populates="chunks")
class KnowledgeReview(UuidPrimaryKeyMixin, Base):
    __tablename__ = "knowledge_reviews"
    __table_args__ = (Index("ix_knowledge_reviews_document_created", "document_id", "created_at"),)

    document_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("knowledge_documents.id", ondelete="CASCADE"), nullable=False
    )
    decision: Mapped[str] = mapped_column(String(20), nullable=False)
    reviewer_role: Mapped[str] = mapped_column(String(30), nullable=False)
    reviewer_ref: Mapped[str] = mapped_column(String(200), nullable=False)
    note: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )

    document = relationship("KnowledgeDocument", back_populates="reviews")


class KnowledgeCase(TimestampMixin, Base):
    """A reviewable, structured troubleshooting case used by the MVP matcher."""

    __tablename__ = "knowledge_cases"
    __table_args__ = (
        Index(
            "ix_knowledge_cases_match",
            "experiment_type",
            "error_type",
            "review_status",
        ),
    )

    id: Mapped[str] = mapped_column(String(100), primary_key=True)
    experiment_type: Mapped[str] = mapped_column(String(100), nullable=False)
    error_type: Mapped[str] = mapped_column(String(100), nullable=False)
    symptom: Mapped[str] = mapped_column(Text, nullable=False)
    normal_state: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    evidence: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list, nullable=False)
    possible_causes: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    solution_steps: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    teacher_notes: Mapped[Optional[str]] = mapped_column(Text)
    facts: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    root_cause_value: Mapped[Optional[str]] = mapped_column(String(200))
    root_cause_status: Mapped[str] = mapped_column(
        String(20), default="unknown", nullable=False
    )
    confirmed_by: Mapped[Optional[str]] = mapped_column(String(200))
    confirmed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    solution_record: Mapped[dict[str, Any]] = mapped_column(
        JSON, default=dict, nullable=False
    )
    ai_generated_fields: Mapped[dict[str, Any]] = mapped_column(
        JSON, default=dict, nullable=False
    )
    source_type: Mapped[str] = mapped_column(
        String(30), default="curated_template", nullable=False
    )
    facts_locked: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    quality_check_passed: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
    )
    review_status: Mapped[str] = mapped_column(
        String(20), default="draft", index=True, nullable=False
    )
    source_ref: Mapped[str] = mapped_column(String(500), nullable=False)
    version: Mapped[str] = mapped_column(String(50), default="1", nullable=False)
    is_test_data: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


class KnowledgeCaseDraft(UuidPrimaryKeyMixin, TimestampMixin, Base):
    """Fact-bound case draft that must pass teacher review before publication."""

    __tablename__ = "knowledge_case_drafts"
    __table_args__ = (
        Index("ix_knowledge_case_drafts_status_created", "status", "created_at"),
        UniqueConstraint(
            "diagnosis_result_id",
            "feedback_id",
            name="uq_knowledge_case_drafts_diagnosis_feedback",
        ),
    )

    diagnosis_result_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("diagnosis_results.id", ondelete="CASCADE"), nullable=False
    )
    feedback_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("diagnosis_feedback.id", ondelete="RESTRICT"), nullable=False
    )
    experiment_type: Mapped[str] = mapped_column(String(100), nullable=False)
    error_type: Mapped[str] = mapped_column(String(100), nullable=False)
    fact_snapshot: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    template_payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    polished_payload: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON)
    quality_checks: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON, default=list, nullable=False
    )
    root_cause: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    solution_record: Mapped[dict[str, Any]] = mapped_column(
        JSON, default=dict, nullable=False
    )
    source_ids: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    allowed_ai_fields: Mapped[list[str]] = mapped_column(
        JSON, default=list, nullable=False
    )
    facts_locked: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    ai_audit: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    status: Mapped[str] = mapped_column(
        String(30), default="draft", index=True, nullable=False
    )
    reviewer_ref: Mapped[Optional[str]] = mapped_column(String(200))
    reviewed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    is_test_data: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
