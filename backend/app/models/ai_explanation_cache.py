from datetime import datetime
from typing import Any, Optional

from sqlalchemy import JSON, DateTime, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.base import UuidPrimaryKeyMixin, utc_now


class AIExplanationCache(UuidPrimaryKeyMixin, Base):
    __tablename__ = "ai_explanation_cache"
    __table_args__ = (Index("ix_ai_explanation_cache_expires", "expires_at"),)

    fingerprint: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    explanation_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    provider: Mapped[Optional[str]] = mapped_column(String(100))
    model_name: Mapped[Optional[str]] = mapped_column(String(200))
    prompt_version: Mapped[str] = mapped_column(String(100), nullable=False)
    schema_version: Mapped[str] = mapped_column(String(100), nullable=False)
    ruleset_version: Mapped[str] = mapped_column(String(100), nullable=False)
    fault_tree_version: Mapped[Optional[str]] = mapped_column(String(100))
    knowledge_version: Mapped[Optional[str]] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    hit_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_hit_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
