"""Create the Phase 8 provider-neutral knowledge framework.

Revision ID: 20260721_0005
Revises: 20260720_0004
Create Date: 2026-07-21
"""

from collections.abc import Sequence
from typing import Optional, Union

import sqlalchemy as sa
from alembic import op

from app.db.vector import PortableVector

revision: str = "20260721_0005"
down_revision: Optional[str] = "20260720_0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table(
        "knowledge_sources",
        sa.Column("source_key", sa.String(length=128), nullable=False),
        sa.Column("source_type", sa.String(length=50), nullable=False),
        sa.Column("title", sa.String(length=300), nullable=False),
        sa.Column("source_uri", sa.String(length=1000), nullable=True),
        sa.Column("version", sa.String(length=100), nullable=True),
        sa.Column("license_name", sa.String(length=200), nullable=True),
        sa.Column("authorization_scope", sa.Text(), nullable=True),
        sa.Column("metadata_json", sa.JSON(), nullable=False),
        sa.Column("is_test_data", sa.Boolean(), nullable=False),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_knowledge_sources_source_key", "knowledge_sources", ["source_key"], unique=True
    )
    op.create_index("ix_knowledge_sources_source_type", "knowledge_sources", ["source_type"])

    op.create_table(
        "knowledge_documents",
        sa.Column("source_id", sa.String(length=36), nullable=False),
        sa.Column("title", sa.String(length=300), nullable=False),
        sa.Column("media_type", sa.String(length=100), nullable=False),
        sa.Column("language", sa.String(length=30), nullable=True),
        sa.Column("storage_uri", sa.String(length=1000), nullable=True),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("parser_name", sa.String(length=100), nullable=False),
        sa.Column("parser_version", sa.String(length=50), nullable=False),
        sa.Column("review_status", sa.String(length=20), nullable=False),
        sa.Column("is_test_data", sa.Boolean(), nullable=False),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["source_id"], ["knowledge_sources.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("source_id", "content_hash", name="uq_knowledge_document_source_hash"),
    )
    op.create_index(
        "ix_knowledge_documents_review_status", "knowledge_documents", ["review_status"]
    )
    op.create_index(
        "ix_knowledge_documents_review_created",
        "knowledge_documents",
        ["review_status", "created_at"],
    )

    op.create_table(
        "knowledge_chunks",
        sa.Column("document_id", sa.String(length=36), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("char_count", sa.Integer(), nullable=False),
        sa.Column("locator_json", sa.JSON(), nullable=False),
        sa.Column("review_status", sa.String(length=20), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.ForeignKeyConstraint(["document_id"], ["knowledge_documents.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("document_id", "chunk_index", name="uq_knowledge_chunk_position"),
    )
    op.create_index("ix_knowledge_chunks_content_hash", "knowledge_chunks", ["content_hash"])
    op.create_index("ix_knowledge_chunks_review_status", "knowledge_chunks", ["review_status"])
    op.create_index(
        "ix_knowledge_chunks_review_document",
        "knowledge_chunks",
        ["review_status", "document_id"],
    )

    op.create_table(
        "knowledge_embeddings",
        sa.Column("chunk_id", sa.String(length=36), nullable=False),
        sa.Column("provider", sa.String(length=100), nullable=False),
        sa.Column("model", sa.String(length=200), nullable=False),
        sa.Column("dimensions", sa.Integer(), nullable=False),
        sa.Column("embedding", PortableVector(), nullable=False),
        sa.Column("is_test_data", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.ForeignKeyConstraint(["chunk_id"], ["knowledge_chunks.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "chunk_id", "provider", "model", name="uq_knowledge_embedding_chunk_model"
        ),
    )
    op.create_index("ix_knowledge_embeddings_model", "knowledge_embeddings", ["provider", "model"])

    op.create_table(
        "knowledge_reviews",
        sa.Column("document_id", sa.String(length=36), nullable=False),
        sa.Column("decision", sa.String(length=20), nullable=False),
        sa.Column("reviewer_ref", sa.String(length=200), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.ForeignKeyConstraint(["document_id"], ["knowledge_documents.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_knowledge_reviews_document_created",
        "knowledge_reviews",
        ["document_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_knowledge_reviews_document_created", table_name="knowledge_reviews")
    op.drop_table("knowledge_reviews")
    op.drop_index("ix_knowledge_embeddings_model", table_name="knowledge_embeddings")
    op.drop_table("knowledge_embeddings")
    op.drop_index("ix_knowledge_chunks_review_document", table_name="knowledge_chunks")
    op.drop_index("ix_knowledge_chunks_review_status", table_name="knowledge_chunks")
    op.drop_index("ix_knowledge_chunks_content_hash", table_name="knowledge_chunks")
    op.drop_table("knowledge_chunks")
    op.drop_index("ix_knowledge_documents_review_created", table_name="knowledge_documents")
    op.drop_index("ix_knowledge_documents_review_status", table_name="knowledge_documents")
    op.drop_table("knowledge_documents")
    op.drop_index("ix_knowledge_sources_source_type", table_name="knowledge_sources")
    op.drop_index("ix_knowledge_sources_source_key", table_name="knowledge_sources")
    op.drop_table("knowledge_sources")
