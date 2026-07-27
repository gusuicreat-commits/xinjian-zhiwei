from collections import defaultdict, deque
from datetime import datetime, timezone
from threading import Lock
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_user
from app.core.config import get_settings
from app.db.session import get_db
from app.models.classroom import (
    Classroom,
    Course,
    DeviceBinding,
    Enrollment,
    TeachingAssignment,
    User,
)
from app.models.device import Device
from app.schemas.auth import (
    ClassroomSummary,
    CurrentUserResponse,
    DeviceAccessSummary,
    LoginRequest,
    SessionResponse,
)
from app.schemas.student import StudentDashboardResponse
from app.services.auth import create_session, user_access
from app.services.student_dashboard import build_student_dashboard

router = APIRouter(prefix="/auth", tags=["auth"])
DatabaseSession = Annotated[Session, Depends(get_db)]
CurrentUser = Annotated[User, Depends(get_current_user)]
_failed_logins: dict[str, deque[float]] = defaultdict(deque)
_failed_login_lock = Lock()


def _login_key(request: Request, username: str) -> str:
    host = request.client.host if request.client else "unknown"
    return f"{host}:{username.lower()}"


def _check_login_limit(key: str, max_failures: int, window_seconds: int) -> None:
    now = datetime.now(timezone.utc).timestamp()
    with _failed_login_lock:
        attempts = _failed_logins[key]
        while attempts and attempts[0] <= now - window_seconds:
            attempts.popleft()
        if len(attempts) >= max_failures:
            raise HTTPException(
                status_code=429,
                detail={
                    "code": "LOGIN_RATE_LIMITED",
                    "message": "Too many failed login attempts",
                },
            )


def _record_login_result(key: str, succeeded: bool) -> None:
    with _failed_login_lock:
        if succeeded:
            _failed_logins.pop(key, None)
        else:
            _failed_logins[key].append(datetime.now(timezone.utc).timestamp())


@router.post("/session", response_model=SessionResponse)
def login(payload: LoginRequest, request: Request, db: DatabaseSession) -> SessionResponse:
    settings = get_settings()
    key = _login_key(request, payload.username)
    _check_login_limit(
        key,
        settings.auth_login_max_failures,
        settings.auth_login_window_seconds,
    )
    result = create_session(
        db,
        payload.username,
        payload.password,
        settings.auth_session_hours,
    )
    if result is None:
        _record_login_result(key, False)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "INVALID_CREDENTIALS", "message": "Invalid credentials"},
        )
    _record_login_result(key, True)
    user, token, session, roles, permissions = result
    return SessionResponse(
        access_token=token,
        expires_at=session.expires_at,
        user_id=user.id,
        username=user.username,
        display_name=user.display_name,
        roles=roles,
        permissions=permissions,
        is_test_data=user.is_test_data,
    )


@router.get("/me", response_model=CurrentUserResponse)
def me(user: CurrentUser, db: DatabaseSession) -> CurrentUserResponse:
    roles, permissions = user_access(db, user.id)
    return CurrentUserResponse(
        id=user.id,
        username=user.username,
        display_name=user.display_name,
        roles=roles,
        permissions=permissions,
        is_test_data=user.is_test_data,
    )


@router.get("/classes", response_model=list[ClassroomSummary])
def my_classes(user: CurrentUser, db: DatabaseSession) -> list[ClassroomSummary]:
    roles, _ = user_access(db, user.id)
    if "admin" in roles:
        rows = db.execute(
            select(Classroom, Course).join(Course, Course.id == Classroom.course_id)
        ).all()
        access_role = "admin"
    elif {"teacher", "teaching_assistant"} & set(roles):
        rows = db.execute(
            select(Classroom, Course)
            .join(Course, Course.id == Classroom.course_id)
            .join(TeachingAssignment, TeachingAssignment.class_id == Classroom.id)
            .where(TeachingAssignment.user_id == user.id)
        ).all()
        access_role = "teacher"
    else:
        rows = db.execute(
            select(Classroom, Course)
            .join(Course, Course.id == Classroom.course_id)
            .join(Enrollment, Enrollment.class_id == Classroom.id)
            .where(Enrollment.user_id == user.id, Enrollment.status == "active")
        ).all()
        access_role = "student"
    return [
        ClassroomSummary(
            id=classroom.id,
            course_code=course.code,
            course_title=course.title,
            code=classroom.code,
            name=classroom.name,
            term=classroom.term,
            access_role=access_role,
            is_test_data=classroom.is_test_data,
        )
        for classroom, course in rows
    ]


def _accessible_devices(db: Session, user: User) -> list[Device]:
    roles, _ = user_access(db, user.id)
    role_set = set(roles)
    if "admin" in role_set:
        query = select(Device).where(Device.is_active.is_(True))
    elif role_set & {"teacher", "teaching_assistant"}:
        query = (
            select(Device)
            .join(DeviceBinding, DeviceBinding.device_id == Device.id)
            .join(
                TeachingAssignment,
                TeachingAssignment.class_id == DeviceBinding.class_id,
            )
            .where(
                TeachingAssignment.user_id == user.id,
                DeviceBinding.is_active.is_(True),
                Device.is_active.is_(True),
            )
        )
    elif "student" in role_set:
        query = (
            select(Device)
            .join(DeviceBinding, DeviceBinding.device_id == Device.id)
            .where(
                DeviceBinding.student_user_id == user.id,
                DeviceBinding.is_active.is_(True),
                Device.is_active.is_(True),
            )
        )
    else:
        return []
    return list(db.scalars(query.distinct().order_by(Device.device_key)))


def _device_is_test_data(device: Device) -> bool:
    return bool(device.metadata_json.get("is_test_data")) or (
        device.device_type is not None
        and ("test" in device.device_type or "synthetic" in device.device_type)
    )


@router.get("/devices", response_model=list[DeviceAccessSummary])
def my_devices(user: CurrentUser, db: DatabaseSession) -> list[DeviceAccessSummary]:
    return [
        DeviceAccessSummary(
            device_id=device.device_key,
            display_name=device.display_name,
            device_type=device.device_type,
            is_test_data=_device_is_test_data(device),
        )
        for device in _accessible_devices(db, user)
    ]


@router.get(
    "/devices/{device_id}/dashboard",
    response_model=StudentDashboardResponse,
)
def scoped_device_dashboard(
    device_id: str,
    user: CurrentUser,
    db: DatabaseSession,
) -> StudentDashboardResponse:
    device = next(
        (
            item
            for item in _accessible_devices(db, user)
            if item.device_key == device_id
        ),
        None,
    )
    if device is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": "DEVICE_NOT_FOUND",
                "message": "Device is not available in the authenticated scope",
            },
        )
    return build_student_dashboard(db, device)
