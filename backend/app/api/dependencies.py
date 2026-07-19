from typing import Annotated, Optional

from fastapi import Depends, Header, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.security import verify_device_token
from app.db.session import get_db
from app.models.device import Device


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
