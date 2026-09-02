from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.api.dependencies import require_review_access
from app.core.config import get_settings
from app.db.session import get_db
from app.models.classroom import AuthSession
from app.models.intervention import InterventionCase
from app.models.knowledge import KnowledgeDocument
from app.schemas.health import (
    DependencyHealthResponse,
    HealthResponse,
    OpsStatusResponse,
)

router = APIRouter(tags=["health"])
DatabaseSession = Annotated[Session, Depends(get_db)]
ReviewAccess = Annotated[None, Depends(require_review_access)]


@router.get("/health", response_model=HealthResponse, summary="Service health check")
async def health_check() -> HealthResponse:
    settings = get_settings()
    return HealthResponse(
        status="ok",
        service=settings.app_name,
        version=settings.app_version,
        environment=settings.app_env,
    )


@router.get("/health/live", response_model=HealthResponse)
async def liveness() -> HealthResponse:
    return await health_check()


@router.get("/health/ready", response_model=DependencyHealthResponse)
def readiness(db: DatabaseSession) -> DependencyHealthResponse:
    try:
        db.execute(text("SELECT 1"))
    except Exception as error:
        raise HTTPException(
            status_code=503,
            detail={"code": "DATABASE_UNAVAILABLE", "message": type(error).__name__},
        ) from error
    return DependencyHealthResponse(
        status="ok",
        dependencies={"database": {"status": "ok", "required": True}},
    )


@router.get("/health/dependencies", response_model=DependencyHealthResponse)
def dependencies(db: DatabaseSession) -> DependencyHealthResponse:
    settings = get_settings()
    ready = readiness(db)
    ready.dependencies["ai"] = {
        "status": "ok" if settings.ai_enabled and settings.ai_api_key else "disabled",
        "required": False,
    }
    ready.dependencies["structured_knowledge"] = {
        "status": "ok",
        "required": True,
    }
    return ready


@router.get("/ops/status", response_model=OpsStatusResponse)
def ops_status(_: ReviewAccess, db: DatabaseSession) -> OpsStatusResponse:
    settings = get_settings()
    formal = db.scalar(
        select(func.count(KnowledgeDocument.id)).where(KnowledgeDocument.is_test_data.is_(False))
    )
    test = db.scalar(
        select(func.count(KnowledgeDocument.id)).where(KnowledgeDocument.is_test_data.is_(True))
    )
    pending = db.scalar(
        select(func.count(InterventionCase.id)).where(
            InterventionCase.status.in_(["open", "claimed", "resolved"])
        )
    )
    active_sessions = db.scalar(
        select(func.count(AuthSession.id)).where(AuthSession.revoked_at.is_(None))
    )
    return OpsStatusResponse(
        version=settings.app_version,
        environment=settings.app_env,
        database="ok",
        ai_enabled=settings.ai_enabled,
        ai_configured=bool(settings.ai_api_key),
        formal_knowledge_documents=int(formal or 0),
        test_knowledge_documents=int(test or 0),
        pending_interventions=int(pending or 0),
        active_sessions=int(active_sessions or 0),
    )
