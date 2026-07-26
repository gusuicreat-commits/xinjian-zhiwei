from datetime import datetime
from typing import Any, Optional

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.base import UuidPrimaryKeyMixin, utc_now


class AICallRecord(UuidPrimaryKeyMixin, Base):
    __tablename__ = "ai_call_records"
    __table_args__ = (
        Index("ix_ai_calls_diagnosis_created", "diagnosis_result_id", "created_at"),
        Index("ix_ai_calls_status_created", "status", "created_at"),
        Index("ix_ai_call_records_episode_created", "episode_id", "created_at"),
    )

    diagnosis_result_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("diagnosis_results.id", ondelete="CASCADE"), nullable=False
    )
    episode_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("diagnosis_episodes.id", ondelete="SET NULL")
    )
    provider: Mapped[Optional[str]] = mapped_column(String(100))
    model: Mapped[Optional[str]] = mapped_column(String(200))
    transport: Mapped[str] = mapped_column(String(50), nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(100), nullable=False)
    prompt_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False)
    duration_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    input_snapshot: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    output_json: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON)
    knowledge_references: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON, default=list, nullable=False
    )
    input_tokens: Mapped[Optional[int]] = mapped_column(Integer)
    output_tokens: Mapped[Optional[int]] = mapped_column(Integer)
    trigger_reason: Mapped[Optional[str]] = mapped_column(String(100))
    cache_status: Mapped[Optional[str]] = mapped_column(String(30))
    route: Mapped[Optional[str]] = mapped_column(String(30))
    route_path: Mapped[Optional[str]] = mapped_column(String(200))
    estimated_cost: Mapped[Optional[float]] = mapped_column(Float)
    latency_ms: Mapped[Optional[int]] = mapped_column(Integer)
    validation_status: Mapped[Optional[str]] = mapped_column(String(30))
    fallback_reason: Mapped[Optional[str]] = mapped_column(String(200))
    error_code: Mapped[Optional[str]] = mapped_column(String(100))
    error_message: Mapped[Optional[str]] = mapped_column(Text)
    is_test_data: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )

    diagnosis_result = relationship("DiagnosisResult", back_populates="ai_call_records")
    episode = relationship("DiagnosisEpisode", back_populates="ai_call_records")
