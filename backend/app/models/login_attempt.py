from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.base import UuidPrimaryKeyMixin


class LoginAttempt(UuidPrimaryKeyMixin, Base):
    """Short-lived capacity reservation; contains no raw login credentials."""

    __tablename__ = "login_attempts"
    __table_args__ = (
        CheckConstraint("status = 'pending' OR status = 'failed'", name="ck_login_attempt_status"),
        Index("ix_login_attempt_key_expiry", "key_hash", "expires_at"),
        Index("ix_login_attempt_expiry", "expires_at"),
    )

    key_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(10), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
