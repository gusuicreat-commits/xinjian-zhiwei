"""Memory governance; ordinary task memory is projected by workflow responses."""

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_user
from app.db.session import get_db
from app.diagnosis.schemas import StrictModel
from app.models import DiagnosisResult, MemoryCleanupPlan, MemoryEvent, User
from app.services import memory_governance as service

router = APIRouter(prefix="/memory", tags=["memory"])
Database = Annotated[Session, Depends(get_db)]
Actor = Annotated[User, Depends(get_current_user)]


class ImpactDecision(StrictModel):
    expected_version: int = Field(ge=0)
    decision: Literal["no_change", "verify_again", "correct_guidance"]
    note: str = Field(min_length=1, max_length=2000)


class CleanupExecution(StrictModel):
    plan_hash: str = Field(pattern=r"^[a-f0-9]{64}$")


def _run(db, action):
    try:
        return action()
    except PermissionError as exc:
        db.rollback()
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except service.MemoryConflict as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc


def _event(db, event_id):
    event = db.get(MemoryEvent, event_id)
    if event is None:
        raise HTTPException(status_code=404, detail="memory event not found")
    return event


@router.get("/events")
def list_events(
    db: Database,
    actor: Actor,
    response: Response,
    after_id: str = "",
    limit: int = Query(default=30, ge=1, le=100),
):
    response.headers["Cache-Control"] = "no-store"
    return _run(db, lambda: service.event_page(db, actor, after_id=after_id, limit=limit))


@router.get("/events/{event_id}/impacts")
def read_impacts(
    event_id: str,
    db: Database,
    actor: Actor,
    response: Response,
    after_id: str = "",
    limit: int = Query(default=50, ge=1, le=100),
):
    response.headers["Cache-Control"] = "no-store"
    # Check role before revealing whether this identifier exists.
    _run(db, lambda: service._scoped_diagnoses(db, actor))
    return _run(
        db,
        lambda: service.impact_page(
            db, actor, _event(db, event_id), after_id=after_id, limit=limit
        ),
    )


@router.post("/events/{event_id}/impacts/{diagnosis_id}/review")
def review_impact(
    event_id: str, diagnosis_id: str, payload: ImpactDecision, db: Database, actor: Actor
):
    _run(db, lambda: service._scoped_diagnoses(db, actor))
    diagnosis = db.get(DiagnosisResult, diagnosis_id)
    if diagnosis is None or not service.can_review_diagnosis(db, actor, diagnosis):
        raise HTTPException(status_code=404, detail="diagnosis not found in current scope")
    review = _run(
        db,
        lambda: service.review_impact(
            db, actor, _event(db, event_id), diagnosis, **payload.model_dump()
        ),
    )
    return {
        "id": review.id,
        "version": review.version,
        "decision": review.decision,
        "note": review.note,
    }


@router.post("/events/{event_id}/clear-caches")
def clear_event_caches(event_id: str, db: Database, actor: Actor):
    _run(db, lambda: service.require_manager(db, actor))
    return _run(db, lambda: service.process_stop_cache(db, _event(db, event_id)))


@router.post("/cleanup-plans", status_code=201)
def create_cleanup_plan(db: Database, actor: Actor, limit: int = Query(default=100, ge=1, le=500)):
    plan = _run(db, lambda: service.plan_cleanup(db, actor, limit=limit))
    return service.cleanup_manifest(plan)


@router.get("/cleanup-plans/{plan_id}")
def read_cleanup_plan(plan_id: str, db: Database, actor: Actor, response: Response):
    _run(db, lambda: service.require_manager(db, actor))
    response.headers["Cache-Control"] = "no-store"
    plan = db.get(MemoryCleanupPlan, plan_id)
    if plan is None or plan.actor_user_id != actor.id:
        raise HTTPException(status_code=404, detail="cleanup plan not found")
    return service.cleanup_manifest(plan)


@router.post("/cleanup-plans/{plan_id}/execute")
def execute_cleanup_plan(plan_id: str, payload: CleanupExecution, db: Database, actor: Actor):
    _run(db, lambda: service.require_manager(db, actor))
    plan = db.get(MemoryCleanupPlan, plan_id)
    if plan is None:
        raise HTTPException(status_code=404, detail="cleanup plan not found")
    return service.cleanup_manifest(
        _run(db, lambda: service.execute_cleanup(db, actor, plan, expected_hash=payload.plan_hash))
    )


@router.get("/events/{event_id}/package-candidates")
def read_package_candidates(
    event_id: str,
    db: Database,
    actor: Actor,
    response: Response,
    after_id: str = "",
    limit: int = Query(default=50, ge=1, le=100),
):
    _run(db, lambda: service.require_manager(db, actor))
    response.headers["Cache-Control"] = "no-store"
    return _run(
        db,
        lambda: service.package_candidates(
            db, actor, _event(db, event_id), after_id=after_id, limit=limit
        ),
    )


@router.get("/events/{event_id}/impacts/{diagnosis_id}/history")
def read_impact_history(
    event_id: str, diagnosis_id: str, db: Database, actor: Actor, response: Response
):
    from app.models import DiagnosisWorkflowRun
    from app.services.current_advice import workflow_context_status

    _run(db, lambda: service._scoped_diagnoses(db, actor))
    diagnosis = db.get(DiagnosisResult, diagnosis_id)
    if diagnosis is None or not service.can_review_diagnosis(db, actor, diagnosis):
        raise HTTPException(status_code=404, detail="diagnosis not found in current scope")
    event = _event(db, event_id)
    if not service.impact_basis(db, event, diagnosis):
        raise HTTPException(status_code=404, detail="impact relationship not found")
    workflow = db.scalar(
        select(DiagnosisWorkflowRun).where(DiagnosisWorkflowRun.diagnosis_result_id == diagnosis.id)
    )
    response.headers["Cache-Control"] = "no-store"
    return {
        "purpose": "historical_review_only",
        "usable_as_current_advice": False,
        "diagnosis_result_id": diagnosis.id,
        "rules": diagnosis.matched_rules,
        "historical_result": workflow.final_result if workflow else None,
        "historical_context_policy": (
            workflow_context_status(db, workflow) if workflow else "unknown"
        ),
        "is_test_data": diagnosis.is_test_data,
    }
