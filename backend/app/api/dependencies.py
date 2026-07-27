import secrets
from typing import Annotated, Optional

from fastapi import Depends, Header, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.security import verify_device_token
from app.db.session import get_db
from app.models.classroom import User
from app.models.device import Device
from app.services.auth import resolve_session, user_access


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
