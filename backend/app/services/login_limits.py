"""PostgreSQL-shared login admission, including password checks still in flight."""

import hashlib
from contextlib import contextmanager
from datetime import timedelta
from threading import RLock

from fastapi import HTTPException
from sqlalchemy import delete, func, select, text
from sqlalchemy.orm import Session

from app.models.base import utc_now
from app.models.login_attempt import LoginAttempt

_LOCK_ID = 693476412831
_MAX_ROWS = 10_000
_sqlite_lock = RLock()


def _limited() -> HTTPException:
    return HTTPException(
        status_code=429,
        detail={
            "code": "LOGIN_RATE_LIMITED",
            "message": "Too many login attempts; try again later",
        },
    )


@contextmanager
def _admission_lock(db: Session):
    # PostgreSQL keeps this lock until commit/rollback. Password hashing is outside it.
    if db.get_bind().dialect.name == "postgresql":
        db.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": _LOCK_ID})
        yield
    else:
        # SQLite is supported for single-process development/tests only.
        with _sqlite_lock:
            yield


def reserve_attempt(db: Session, key: str, maximum: int, window_seconds: int) -> str:
    key_hash = hashlib.sha256(key.encode()).hexdigest()
    with _admission_lock(db):
        now = utc_now()
        expired = select(LoginAttempt.id).where(LoginAttempt.expires_at <= now).limit(500)
        db.execute(delete(LoginAttempt).where(LoginAttempt.id.in_(expired)))
        total = db.scalar(select(func.count()).select_from(LoginAttempt))
        used = db.scalar(
            select(func.count())
            .select_from(LoginAttempt)
            .where(
                LoginAttempt.key_hash == key_hash,
                LoginAttempt.expires_at > now,
            )
        )
        if total >= _MAX_ROWS or used >= maximum:
            db.commit()  # persist bounded cleanup, release the admission lock
            raise _limited()
        attempt = LoginAttempt(
            key_hash=key_hash,
            status="pending",
            expires_at=now + timedelta(seconds=window_seconds),
        )
        db.add(attempt)
        db.flush()
        attempt_id = attempt.id
        db.commit()
    return attempt_id


def finish_attempt(db: Session, attempt_id: str, *, succeeded: bool, window_seconds: int) -> None:
    """Success is committed together with its AuthSession by create_session."""
    with _admission_lock(db):
        now = utc_now()
        attempt = db.scalar(
            select(LoginAttempt)
            .where(
                LoginAttempt.id == attempt_id,
            )
            .execution_options(populate_existing=True)
        )
        expires_at = attempt.expires_at if attempt else now
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=now.tzinfo)
        if attempt is None or attempt.status != "pending" or expires_at <= now:
            db.rollback()
            raise _limited()
        if succeeded:
            # A successful request must not erase reservations owned by other requests.
            db.execute(
                delete(LoginAttempt).where(
                    LoginAttempt.key_hash == attempt.key_hash,
                    (LoginAttempt.status == "failed") | (LoginAttempt.id == attempt_id),
                )
            )
        else:
            attempt.status = "failed"
            attempt.expires_at = now + timedelta(seconds=window_seconds)
            db.commit()
