from datetime import timedelta

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from shared_authorization import authorize_review_fixture
from shared_student_authorization import demo_student_actor
from sqlalchemy import delete, func, select

from app.ai.diagnosis_graph import build_diagnosis_graph
from app.core.config import Settings
from app.core.security import hash_password
from app.diagnosis.workflow_schemas import (
    DiagnosisWorkflowReviewRequest,
    DiagnosisWorkflowStartRequest,
)
from app.models import Device, TeachingAssignment, User
from app.models.base import utc_now
from app.models.classroom import AuthSession, user_roles
from app.models.diagnosis_workflow import DiagnosisWorkflowReview
from app.services.auth import AuthorizationDenied
from app.services.diagnosis_workflow import review_workflow, start_workflow


def review_setup(db):
    graph = build_diagnosis_graph(InMemorySaver())
    settings = Settings(
        ai_enabled=False, diagnosis_rag_trigger_score=1.0, diagnosis_teacher_review_score=1.0
    )
    device = db.scalar(select(Device))
    workflow = start_workflow(
        db,
        graph,
        device,
        settings,
        DiagnosisWorkflowStartRequest(lookback_seconds=60),
        student_actor=demo_student_actor(db, device),
    )
    teacher = User(
        username="guard-teacher",
        display_name="合成教师",
        password_hash=hash_password("synthetic", iterations=1000),
        is_test_data=True,
    )
    db.add(teacher)
    db.commit()
    actor = authorize_review_fixture(db, teacher, workflow)
    return graph, settings, workflow, teacher, actor


@pytest.mark.parametrize("revocation", ["role", "assignment", "inactive", "session", "expiry"])
def test_current_review_authorization_rejects_without_business_effect(api_context, revocation):
    with api_context["session_factory"]() as db:
        graph, settings, workflow, teacher, actor = review_setup(db)
        if revocation == "role":
            db.execute(delete(user_roles).where(user_roles.c.user_id == teacher.id))
        elif revocation == "assignment":
            db.execute(delete(TeachingAssignment).where(TeachingAssignment.user_id == teacher.id))
        elif revocation == "inactive":
            teacher.is_active = False
        elif revocation == "session":
            db.get(AuthSession, actor.session_id).revoked_at = utc_now()
        else:
            db.get(AuthSession, actor.session_id).expires_at = utc_now() - timedelta(seconds=1)
        db.commit()
        with pytest.raises(AuthorizationDenied):
            review_workflow(
                db,
                graph,
                workflow,
                teacher,
                settings,
                DiagnosisWorkflowReviewRequest(action="reject"),
            )
        db.rollback()
        db.refresh(workflow)
        assert workflow.status == "waiting_teacher"
        assert workflow.resume_count == 0
        assert db.scalar(select(func.count()).select_from(DiagnosisWorkflowReview)) == 0


def test_terminal_node_rechecks_after_intermediate_commit(api_context):
    with api_context["session_factory"]() as db:
        graph, settings, workflow, teacher, actor = review_setup(db)
        original = graph.invoke

        def revoke_then_invoke(*args, **kwargs):
            # Models the earlier graph commit ending the route's protected transaction.
            db.commit()
            db.execute(delete(TeachingAssignment).where(TeachingAssignment.user_id == teacher.id))
            db.commit()
            return original(*args, **kwargs)

        graph.invoke = revoke_then_invoke
        with pytest.raises(AuthorizationDenied):
            review_workflow(
                db,
                graph,
                workflow,
                teacher,
                settings,
                DiagnosisWorkflowReviewRequest(action="reject"),
            )
        db.rollback()
        db.refresh(workflow)
        assert workflow.status == "waiting_teacher"
        assert db.scalar(select(func.count()).select_from(DiagnosisWorkflowReview)) == 0


def test_old_user_object_cannot_authorize_direct_review(api_context):
    with api_context["session_factory"]() as db:
        graph, settings, workflow, teacher, actor = review_setup(db)
        del teacher._actor_context
        with pytest.raises(AuthorizationDenied, match="current authorization"):
            review_workflow(
                db,
                graph,
                workflow,
                teacher,
                settings,
                DiagnosisWorkflowReviewRequest(action="approve"),
            )


def test_empty_direct_graph_resume_cannot_reject_without_current_reviewer(api_context):
    from langgraph.runtime import Runtime

    from app.ai.diagnosis_graph import DiagnosisGraphContext, reject_result

    with api_context["session_factory"]() as db:
        graph, settings, workflow, teacher, actor = review_setup(db)
        checkpoint = graph.get_state({"configurable": {"thread_id": workflow.graph_thread_id}})
        state = {**checkpoint.values, "teacher_review": {}}
        runtime = Runtime(
            context=DiagnosisGraphContext(
                db=db,
                device=db.get(Device, workflow.device_id),
                settings=settings,
            )
        )
        with pytest.raises(AuthorizationDenied):
            reject_result(state, runtime)
        db.rollback()
        db.refresh(workflow)
        assert workflow.status == "waiting_teacher"
        assert db.scalar(select(func.count()).select_from(DiagnosisWorkflowReview)) == 0
