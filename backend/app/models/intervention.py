from datetime import datetime
from typing import Any, Optional

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Index, Integer, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.base import TimestampMixin, UuidPrimaryKeyMixin


class InterventionCase(UuidPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "intervention_cases"
    __table_args__ = (
        Index(
            "uq_intervention_legacy_diagnosis",
            "diagnosis_result_id",
            unique=True,
            postgresql_where=text("episode_id IS NULL"),
            sqlite_where=text("episode_id IS NULL"),
        ),
        Index(
            "uq_intervention_active_episode",
            "episode_id",
            unique=True,
            postgresql_where=text(
                "episode_id IS NOT NULL AND status IN ('open','claimed','unconfirmed')"
            ),
            sqlite_where=text(
                "episode_id IS NOT NULL AND status IN ('open','claimed','unconfirmed')"
            ),
        ),
    )

    diagnosis_result_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("diagnosis_results.id", ondelete="CASCADE"), nullable=False
    )
    episode_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("diagnosis_episodes.id", ondelete="RESTRICT")
    )
    class_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("classes.id", ondelete="SET NULL"), index=True
    )
    assigned_teacher_user_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="SET NULL")
    )
    status: Mapped[str] = mapped_column(String(30), default="open", nullable=False)
    version_no: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    resolution_summary: Mapped[Optional[str]] = mapped_column(Text)
    is_test_data: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


class InterventionEvent(UuidPrimaryKeyMixin, Base):
    __tablename__ = "intervention_events"

    case_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("intervention_cases.id", ondelete="CASCADE"), index=True
    )
    actor_user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    action: Mapped[str] = mapped_column(String(30), nullable=False)
    from_status: Mapped[Optional[str]] = mapped_column(String(30))
    to_status: Mapped[Optional[str]] = mapped_column(String(30))
    note: Mapped[Optional[str]] = mapped_column(Text)
    is_private: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSON, default=dict, nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ClassroomMessage(UuidPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "classroom_messages"

    class_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("classes.id", ondelete="CASCADE"), index=True
    )
    author_user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    message: Mapped[str] = mapped_column(Text, nullable=False)
    audience: Mapped[str] = mapped_column(String(30), default="class", nullable=False)
    retracted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    retracted_by_user_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="SET NULL")
    )
    is_test_data: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
