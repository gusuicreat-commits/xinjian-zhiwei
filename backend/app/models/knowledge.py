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
from app.db.vector import PortableVector
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
    embeddings = relationship(
        "KnowledgeEmbedding", back_populates="chunk", cascade="all, delete-orphan"
    )


class KnowledgeEmbedding(UuidPrimaryKeyMixin, Base):
    __tablename__ = "knowledge_embeddings"
    __table_args__ = (
        UniqueConstraint(
            "chunk_id", "provider", "model", name="uq_knowledge_embedding_chunk_model"
        ),
        Index("ix_knowledge_embeddings_model", "provider", "model"),
    )

    chunk_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("knowledge_chunks.id", ondelete="CASCADE"), nullable=False
    )
    provider: Mapped[str] = mapped_column(String(100), nullable=False)
    model: Mapped[str] = mapped_column(String(200), nullable=False)
    dimensions: Mapped[int] = mapped_column(Integer, nullable=False)
    embedding: Mapped[list[float]] = mapped_column(PortableVector(), nullable=False)
    is_test_data: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )

    chunk = relationship("KnowledgeChunk", back_populates="embeddings")


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
