from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.dependencies import require_any_role
from app.db.session import get_db
from app.models.classroom import DeviceBinding, TeachingAssignment, User
from app.schemas.student import ExperimentSessionRelease
from app.schemas.teacher import TeacherDashboardResponse
from app.services.auth import current_actor, user_access
from app.services.teacher_dashboard import build_teacher_dashboard

router = APIRouter(prefix="/teacher", tags=["teacher"])
DatabaseSession = Annotated[Session, Depends(get_db)]
TeacherUser = Annotated[User, Depends(require_any_role("teacher", "admin"))]


@router.get("/dashboard", response_model=TeacherDashboardResponse)
def get_teacher_dashboard(
    actor: TeacherUser,
    db: DatabaseSession,
) -> TeacherDashboardResponse:
    roles, _ = user_access(db, actor.id)
    if "admin" in roles:
        return build_teacher_dashboard(db, actor_context=current_actor(actor))
    device_ids = set(
        db.scalars(
            select(DeviceBinding.device_id)
            .join(
                TeachingAssignment,
                TeachingAssignment.class_id == DeviceBinding.class_id,
            )
            .where(
                TeachingAssignment.user_id == actor.id,
                DeviceBinding.is_active.is_(True),
            )
            .distinct()
        )
    )
    class_ids = set(
        db.scalars(
            select(TeachingAssignment.class_id).where(TeachingAssignment.user_id == actor.id)
        )
    )
    return build_teacher_dashboard(
        db, allowed_device_ids=device_ids, allowed_class_ids=class_ids,
        actor_context=current_actor(actor),
    )


@router.get("/experiment-sessions")
def managed_sessions(actor: TeacherUser, db: DatabaseSession):
    from app.services.data_scope import ScopeViolation
    from app.services.experiment_sessions import list_managed_sessions

    try:
        return list_managed_sessions(db, actor)
    except ScopeViolation as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


@router.post("/experiment-sessions/{session_id}/release")
def release_managed_session(
    session_id: str, payload: ExperimentSessionRelease, actor: TeacherUser, db: DatabaseSession
):
    from app.services.data_scope import ScopeConflict, ScopeViolation
    from app.services.experiment_sessions import release_session

    try:
        return release_session(
            db,
            actor,
            session_id=session_id,
            request_id=payload.request_id,
            expected_version=payload.expected_version,
            reason=payload.reason,
        )
    except ScopeViolation as exc:
        db.rollback()
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ScopeConflict as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/experiment-sessions/{session_id}")
def managed_session_receipt_scope(session_id: str, actor: TeacherUser, db: DatabaseSession):
    from app.models import ExperimentSession
    from app.services.data_scope import ScopeViolation
    from app.services.experiment_sessions import assert_session_management, managed_session_summary

    session = db.get(ExperimentSession, session_id)
    try:
        assert_session_management(db, actor, session)
        return managed_session_summary(db, session)
    except ScopeViolation as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
