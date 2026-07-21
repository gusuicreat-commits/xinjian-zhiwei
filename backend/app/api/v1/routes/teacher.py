from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.dependencies import require_review_access
from app.db.session import get_db
from app.schemas.teacher import TeacherDashboardResponse, TeacherSessionResponse
from app.services.teacher_dashboard import build_teacher_dashboard

router = APIRouter(prefix="/teacher", tags=["teacher"])
DatabaseSession = Annotated[Session, Depends(get_db)]
ReviewAccess = Annotated[None, Depends(require_review_access)]


@router.post("/session", response_model=TeacherSessionResponse)
def create_teacher_session(_: ReviewAccess) -> TeacherSessionResponse:
    return TeacherSessionResponse(
        auth_mode="review_token_placeholder",
        notice="正式教师账号与角色尚未建立；当前使用默认关闭的审阅令牌作为临时边界。",
    )


@router.get("/dashboard", response_model=TeacherDashboardResponse)
def get_teacher_dashboard(
    _: ReviewAccess,
    db: DatabaseSession,
) -> TeacherDashboardResponse:
    return build_teacher_dashboard(db)
