from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.dependencies import require_any_role
from app.db.session import get_db
from app.models.classroom import DeviceBinding, TeachingAssignment, User
from app.schemas.teacher import TeacherDashboardResponse
from app.services.auth import user_access
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
        return build_teacher_dashboard(db)
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
    return build_teacher_dashboard(db, allowed_device_ids=device_ids)
