"""Structured case availability for the teacher dashboard."""

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.models.knowledge import KnowledgeCase
from app.schemas.knowledge import KnowledgeStatusResponse
from app.services.auth import ActorContext, authorize_actor


def get_global_knowledge_status(
    db: Session, settings: Settings, *, actor_context=None
) -> KnowledgeStatusResponse:
    if isinstance(actor_context, ActorContext):
        authorize_actor(db, actor_context, "dashboard.read")
    case_count = db.scalar(select(func.count()).select_from(KnowledgeCase)) or 0
    approved_case_count = (
        db.scalar(
            select(func.count())
            .select_from(KnowledgeCase)
            .where(
                KnowledgeCase.review_status == "approved",
                KnowledgeCase.is_test_data.is_(False),
            )
        )
        or 0
    )
    content_available = approved_case_count > 0
    if case_count == 0:
        notice = "结构化知识库已建立，但尚未同步知识案例。"
    elif not content_available:
        notice = "案例已同步，但尚无通过审核的非测试结构化案例。"
    else:
        notice = "已启用基于实验类型、错误类型和证据的结构化案例匹配。"
    return KnowledgeStatusResponse(
        content_available=content_available,
        case_count=case_count,
        approved_case_count=approved_case_count,
        notice=notice,
    )
