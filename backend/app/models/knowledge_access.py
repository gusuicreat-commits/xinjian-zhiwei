"""Explicit source-level grants; license text is never an access-control list."""

from sqlalchemy import CheckConstraint, ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.base import TimestampMixin, UuidPrimaryKeyMixin


class KnowledgeSourceGrant(UuidPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "knowledge_source_grants"
    __table_args__ = (
        UniqueConstraint("source_id", "user_id", "capability", name="uq_knowledge_source_grant"),
        CheckConstraint(
            "CAST(capability AS TEXT) IN ('organize', 'review')", name="ck_source_grant_capability"
        ),
        Index("ix_source_grants_user_source", "user_id", "source_id"),
    )
    source_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("knowledge_sources.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    capability: Mapped[str] = mapped_column(String(20), nullable=False)
