import secrets
from collections.abc import Callable
from dataclasses import dataclass
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
    *,
    finalize_success: Optional[Callable[[], None]] = None,
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
    if finalize_success is not None:
        finalize_success()
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
    user = db.get(User, session.user_id)
    if user is not None:
        user._actor_context = ActorContext(user.id, session.id)
    return user


@dataclass(frozen=True)
class ActorContext:
    """Server-owned identity reference; never a cached authorization decision."""

    user_id: str
    session_id: str | None = None
    mode: str = "session"


class AuthorizationDenied(PermissionError):
    def __init__(self, status_code=403):
        self.status_code = status_code
        super().__init__("current authorization is no longer valid")


def current_actor(user: User) -> ActorContext:
    actor = getattr(user, "_actor_context", None)
    if not isinstance(actor, ActorContext) or actor.user_id != user.id:
        raise AuthorizationDenied(401)
    return actor


def authorize_actor(db: Session, actor: ActorContext, permission: str) -> User:
    """Protect supporting authorization rows until the caller's short commit.

    Order within this boundary: user, auth session, user-role edges, roles,
    role-permission edges, permissions. FOR SHARE allows independent commands
    while conflicting with revocation UPDATE/DELETE, including direct SQL.
    Call only after domain locks; never retain across external I/O.
    """
    if not isinstance(actor, ActorContext):
        raise AuthorizationDenied(401)
    user = db.scalar(
        select(User)
        .where(User.id == actor.user_id)
        .with_for_update(read=True)
        .execution_options(populate_existing=True)
    )
    if user is None or not user.is_active:
        raise AuthorizationDenied(401)
    if actor.mode == "session":
        session = db.scalar(
            select(AuthSession)
            .where(AuthSession.id == actor.session_id, AuthSession.user_id == actor.user_id)
            .with_for_update(read=True)
            .execution_options(populate_existing=True)
        )
        now = utc_now()
        if session is None or session.revoked_at is not None:
            raise AuthorizationDenied(401)
        expiry = session.expires_at
        if expiry.tzinfo is None:
            expiry = expiry.replace(tzinfo=now.tzinfo)
        if expiry <= now:
            raise AuthorizationDenied(401)
    elif actor.mode != "local_admin":
        raise AuthorizationDenied(401)
    role_ids = list(
        db.scalars(
            select(user_roles.c.role_id)
            .where(user_roles.c.user_id == actor.user_id)
            .order_by(user_roles.c.role_id)
            .with_for_update(read=True)
        )
    )
    roles = list(
        db.scalars(
            select(Role)
            .where(Role.id.in_(role_ids))
            .order_by(Role.id)
            .with_for_update(read=True)
            .execution_options(populate_existing=True)
        )
    )
    permission_ids = list(
        db.scalars(
            select(role_permissions.c.permission_id)
            .where(role_permissions.c.role_id.in_(role_ids))
            .order_by(role_permissions.c.role_id, role_permissions.c.permission_id)
            .with_for_update(read=True)
        )
    )
    permissions = list(
        db.scalars(
            select(Permission.code)
            .where(Permission.id.in_(permission_ids))
            .order_by(Permission.id)
            .with_for_update(read=True)
        )
    )
    if permission not in permissions or (
        actor.mode == "local_admin" and not any(role.code == "admin" for role in roles)
    ):
        raise AuthorizationDenied()
    user._actor_context = actor
    return user
