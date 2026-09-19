import secrets
from typing import Annotated, Optional

from fastapi import Depends, Header, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.security import verify_device_token
from app.db.session import get_db
from app.models.classroom import ExperimentSession, User
from app.models.device import Device
from app.services.auth import resolve_session, user_access
from app.services.data_scope import (
    ScopeConflict,
    ScopeViolation,
    assert_student_session_access,
    find_active_experiment_session,
    is_demo_device,
    is_demo_session,
    resolve_experiment_session,
)


def require_review_access(
    settings: Annotated[Settings, Depends(get_settings)],
    x_review_token: Annotated[Optional[str], Header(alias="X-Review-Token")] = None,
) -> None:
    expected = settings.review_access_token
    if not expected:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "REVIEW_ACCESS_NOT_CONFIGURED",
                "message": "Review access is not configured",
            },
        )
    if not x_review_token or not secrets.compare_digest(x_review_token, expected):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "INVALID_REVIEW_TOKEN", "message": "Invalid review credentials"},
        )


def get_authenticated_device(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    x_device_token: Annotated[Optional[str], Header(alias="X-Device-Token")] = None,
    x_device_id: Annotated[Optional[str], Header(alias="X-Device-ID")] = None,
) -> Device:
    device_key = request.path_params.get("device_id") or x_device_id
    if not device_key or not x_device_token:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={
                "code": "DEVICE_CREDENTIALS_REQUIRED",
                "message": "X-Device-ID and X-Device-Token are required",
            },
        )

    device = db.scalar(select(Device).where(Device.device_key == device_key))
    if (
        device is None
        or not device.is_active
        or not verify_device_token(x_device_token, device.token_hash)
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "INVALID_DEVICE_TOKEN", "message": "Invalid device credentials"},
            headers={"WWW-Authenticate": "DeviceToken"},
        )
    return device


def get_current_user(
    db: Annotated[Session, Depends(get_db)],
    authorization: Annotated[Optional[str], Header()] = None,
) -> User:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "SESSION_REQUIRED", "message": "Bearer session is required"},
        )
    user = resolve_session(db, authorization[7:])
    if user is None or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "INVALID_SESSION", "message": "Session is invalid or expired"},
        )
    return user


def get_student_device(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    authorization: Annotated[Optional[str], Header()] = None,
    x_device_token: Annotated[Optional[str], Header(alias="X-Device-Token")] = None,
    x_device_id: Annotated[Optional[str], Header(alias="X-Device-ID")] = None,
    session_id: Annotated[Optional[str], Header(alias="X-Experiment-Session-ID")] = None,
) -> Device:
    """Student operations never treat a production device secret as a human login."""
    try:
        if authorization is not None:
            user = get_current_user(db, authorization)
            _, permissions = user_access(db, user.id)
            needed = (
                "feedback.create" if request.url.path.endswith("/feedback") else "dashboard.read"
            )
            if needed not in permissions:
                raise ScopeViolation("student operation permission was revoked")
            device_key = request.path_params.get("device_id") or x_device_id
            device = db.scalar(select(Device).where(Device.device_key == device_key))
            if device is None or not device.is_active:
                raise ScopeViolation("device is not available")
            if session_id is None:
                owned = list(
                    db.scalars(
                        select(ExperimentSession).where(
                            ExperimentSession.device_id == device.id,
                            ExperimentSession.student_user_id == user.id,
                            ExperimentSession.status == "active",
                            ExperimentSession.ended_at.is_(None),
                        )
                    )
                )
                if len(owned) != 1:
                    raise ScopeConflict("select one active experiment session")
                session = owned[0]
            else:
                session = resolve_experiment_session(db, device, session_id, require_active=False)
            # Closed-session receipt reads retain the original identity; write routes
            # independently reject new work in a closed session.
            receipt_read = request.url.path.endswith("/feedback-recovery")
            feedback_retry = request.url.path.endswith("/feedback")
            assert_student_session_access(
                db, user, session, require_active=not (receipt_read or feedback_retry)
            )
            request.state.student_auth_mode = "student_account"
            request.state.student_user_id = user.id
        else:
            device = get_authenticated_device(request, db, x_device_token, x_device_id)
            if not is_demo_device(device):
                raise HTTPException(status_code=401, detail="student account login required")
            session = (
                resolve_experiment_session(db, device, session_id, require_active=False)
                if session_id
                else find_active_experiment_session(db, device)
            )
            if session is not None and not is_demo_session(db, session):
                raise HTTPException(status_code=401, detail="student account login required")
            if session is not None and not db.get(User, session.student_user_id).is_active:
                raise ScopeViolation("student account is inactive")
            request.state.student_auth_mode = "device_credential_placeholder"
        request.state.student_experiment_session = session
        return device
    except ScopeViolation as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ScopeConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


def require_permission(permission_code: str):
    def dependency(
        user: Annotated[User, Depends(get_current_user)],
        db: Annotated[Session, Depends(get_db)],
    ) -> User:
        _, permissions = user_access(db, user.id)
        if permission_code not in permissions:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={
                    "code": "PERMISSION_DENIED",
                    "message": f"Permission {permission_code} is required",
                },
            )
        return user

    return dependency


def revalidate_student_access(request: Request, db: Session):
    """Long-running operations must not deliver to an identity revoked during I/O."""
    db.expire_all()
    return get_student_device(
        request,
        db,
        authorization=request.headers.get("Authorization"),
        x_device_token=request.headers.get("X-Device-Token"),
        x_device_id=request.headers.get("X-Device-ID"),
        session_id=request.headers.get("X-Experiment-Session-ID"),
    )


def require_any_role(*role_codes: str):
    allowed_roles = set(role_codes)

    def dependency(
        user: Annotated[User, Depends(get_current_user)],
        db: Annotated[Session, Depends(get_db)],
    ) -> User:
        roles, _ = user_access(db, user.id)
        if not allowed_roles.intersection(roles):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={
                    "code": "ROLE_DENIED",
                    "message": f"One of these roles is required: {', '.join(role_codes)}",
                },
            )
        return user

    return dependency
