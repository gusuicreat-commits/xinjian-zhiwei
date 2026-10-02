from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_user
from app.core.config import get_settings
from app.db.session import get_db
from app.models.classroom import (
    Classroom,
    Course,
    DeviceBinding,
    Enrollment,
    ExperimentAssignment,
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
from app.services.auth import AuthorizationDenied, create_session, revoke_session, user_access
from app.services.data_scope import (
    ScopeConflict,
    ScopeViolation,
    assert_student_session_access,
    find_active_experiment_session,
    teacher_has_class_access,
)
from app.services.login_limits import finish_attempt, reserve_attempt
from app.services.student_dashboard import build_student_dashboard

router = APIRouter(prefix="/auth", tags=["auth"])
DatabaseSession = Annotated[Session, Depends(get_db)]
CurrentUser = Annotated[User, Depends(get_current_user)]


def _login_key(request: Request, username: str) -> str:
    host = request.client.host if request.client else "unknown"
    return f"{host}:{username.lower()}"


@router.post("/session", response_model=SessionResponse)
def login(payload: LoginRequest, request: Request, db: DatabaseSession) -> SessionResponse:
    settings = get_settings()
    key = _login_key(request, payload.username)
    attempt_id = reserve_attempt(
        db,
        key,
        settings.auth_login_max_failures,
        settings.auth_login_window_seconds,
    )
    result = create_session(
        db,
        payload.username,
        payload.password,
        settings.auth_session_hours,
        finalize_success=lambda: finish_attempt(
            db,
            attempt_id,
            succeeded=True,
            window_seconds=settings.auth_login_window_seconds,
        ),
    )
    if result is None:
        finish_attempt(
            db,
            attempt_id,
            succeeded=False,
            window_seconds=settings.auth_login_window_seconds,
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "INVALID_CREDENTIALS", "message": "Invalid credentials"},
        )
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


@router.delete("/session", status_code=204)
def logout(request: Request, db: DatabaseSession) -> Response:
    authorization = request.headers.get("Authorization", "")
    if not authorization.startswith("Bearer ") or not authorization[7:]:
        raise AuthorizationDenied(401)
    revoke_session(db, authorization[7:])
    return Response(status_code=204, headers={"Cache-Control": "no-store"})


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
    teaching = (
        set(
            db.scalars(
                select(TeachingAssignment.class_id).where(TeachingAssignment.user_id == user.id)
            )
        )
        if "teacher" in roles
        else set()
    )
    studying = (
        set(
            db.scalars(
                select(Enrollment.class_id).where(
                    Enrollment.user_id == user.id, Enrollment.status == "active"
                )
            )
        )
        if "student" in roles
        else set()
    )
    query = select(Classroom, Course).join(Course, Course.id == Classroom.course_id)
    if "admin" not in roles:
        query = query.where(Classroom.id.in_(teaching | studying), Classroom.is_active.is_(True))
    return [
        ClassroomSummary(
            id=classroom.id,
            course_code=course.code,
            course_title=course.title,
            code=classroom.code,
            name=classroom.name,
            term=classroom.term,
            access_role=(
                "admin"
                if "admin" in roles
                else "teacher"
                if classroom.id in teaching
                else "student"
            ),
            is_test_data=classroom.is_test_data,
        )
        for classroom, course in db.execute(query.order_by(Classroom.id)).all()
    ]


def _accessible_devices(db: Session, user: User) -> list[Device]:
    roles, _ = user_access(db, user.id)
    query = select(Device).where(Device.is_active.is_(True))
    if "admin" not in roles:
        predicates = []
        if "teacher" in roles:
            predicates.append(
                DeviceBinding.class_id.in_(
                    select(TeachingAssignment.class_id).where(TeachingAssignment.user_id == user.id)
                )
            )
        if "student" in roles:
            predicates.append(
                (DeviceBinding.student_user_id == user.id)
                & DeviceBinding.class_id.in_(
                    select(Enrollment.class_id).where(
                        Enrollment.user_id == user.id, Enrollment.status == "active"
                    )
                )
            )
        if not predicates:
            return []
        query = (
            query.join(DeviceBinding, DeviceBinding.device_id == Device.id)
            .join(Classroom, Classroom.id == DeviceBinding.class_id)
            .where(
                DeviceBinding.is_active.is_(True), Classroom.is_active.is_(True), or_(*predicates)
            )
        )
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
        (item for item in _accessible_devices(db, user) if item.device_key == device_id),
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
    try:
        session = find_active_experiment_session(db, device)
        if session is not None:
            assignment = db.get(ExperimentAssignment, session.experiment_assignment_id)
            if not teacher_has_class_access(db, user, assignment.class_id):
                assert_student_session_access(db, user, session)
        return build_student_dashboard(db, device, session.id if session else None)
    except ScopeViolation as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ScopeConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
