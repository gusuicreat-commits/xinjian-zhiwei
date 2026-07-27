import secrets
from datetime import timedelta
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.security import hash_session_token, verify_password
from app.models.base import utc_now
from app.models.classroom import (
    AuditEvent,
    AuthSession,
    Permission,
    Role,
    User,
    role_permissions,
    user_roles,
)


def user_access(db: Session, user_id: str) -> tuple[list[str], list[str]]:
    roles = list(
        db.scalars(
            select(Role.code)
            .join(user_roles, user_roles.c.role_id == Role.id)
            .where(user_roles.c.user_id == user_id)
            .order_by(Role.code)
        )
    )
    permissions = list(
        db.scalars(
            select(Permission.code)
            .join(
                role_permissions,
                role_permissions.c.permission_id == Permission.id,
            )
            .join(user_roles, user_roles.c.role_id == role_permissions.c.role_id)
            .where(user_roles.c.user_id == user_id)
            .distinct()
            .order_by(Permission.code)
        )
    )
    return roles, permissions


def create_session(
    db: Session,
    username: str,
    password: str,
    session_hours: int,
) -> Optional[tuple[User, str, AuthSession, list[str], list[str]]]:
    user = db.scalar(select(User).where(User.username == username))
    if user is None or not user.is_active or not verify_password(password, user.password_hash):
        return None
    raw_token = secrets.token_urlsafe(48)
    now = utc_now()
    session = AuthSession(
        user_id=user.id,
        token_hash=hash_session_token(raw_token),
        expires_at=now + timedelta(hours=session_hours),
    )
    roles, permissions = user_access(db, user.id)
    db.add(session)
    db.flush()
    db.add(
        AuditEvent(
            actor_user_id=user.id,
            action="auth.login",
            resource_type="auth_session",
            resource_id=session.id,
            details_json={"roles": roles},
            is_test_data=user.is_test_data,
            created_at=now,
        )
    )
    db.commit()
    db.refresh(session)
    return user, raw_token, session, roles, permissions


def resolve_session(db: Session, raw_token: str) -> Optional[User]:
    session = db.scalar(
        select(AuthSession).where(AuthSession.token_hash == hash_session_token(raw_token))
    )
    now = utc_now()
    if session is None or session.revoked_at is not None:
        return None
    expires_at = session.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=now.tzinfo)
    if expires_at <= now:
        return None
    return db.get(User, session.user_id)
