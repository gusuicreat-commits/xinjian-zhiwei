"""Revocation interleavings against real PostgreSQL, in disposable schemas."""

from concurrent.futures import ThreadPoolExecutor
from threading import Event

import pytest
from sqlalchemy import delete, func, select, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import sessionmaker
from test_migration_r2 import migration_db as _migration_db
from test_shared_authorization import review_setup

from app.diagnosis.workflow_schemas import DiagnosisWorkflowReviewRequest
from app.models import (
    Classroom,
    Course,
    Device,
    ExperimentAssignment,
    ExperimentSession,
    TeachingAssignment,
    User,
)
from app.models.base import utc_now
from app.models.diagnosis_workflow import DiagnosisWorkflowReview, DiagnosisWorkflowRun
from app.services.auth import AuthorizationDenied
from app.services.data_scope import authorize_workflow_review
from app.services.diagnosis_workflow import review_workflow

migration_db = _migration_db


def seed(factory):
    with factory() as db:
        course = Course(code="race", title="Race", is_test_data=True)
        device = Device(device_key="race", device_type="test-fixture", token_hash="synthetic")
        student = User(
            username="race-student",
            display_name="Test",
            password_hash="unusable",
            is_test_data=True,
        )
        db.add_all([course, device, student])
        db.flush()
        classroom = Classroom(course_id=course.id, code="race", name="Race", is_test_data=True)
        db.add(classroom)
        db.flush()
        assignment = ExperimentAssignment(
            class_id=classroom.id, title="Race", status="published", is_test_data=True
        )
        db.add(assignment)
        db.flush()
        db.add(
            ExperimentSession(
                device_id=device.id,
                student_user_id=student.id,
                experiment_assignment_id=assignment.id,
                status="active",
                started_at=utc_now(),
                is_test_data=True,
            )
        )
        db.commit()
        graph, settings, workflow, teacher, actor = review_setup(db)
        return graph, settings, workflow.id, teacher.id, actor


def test_revoke_commits_while_review_waits_on_workflow_lock(migration_db):
    engine, migrate = migration_db
    migrate("upgrade", "head")
    factory = sessionmaker(engine, expire_on_commit=False)
    graph, settings, wid, uid, actor = seed(factory)
    entered = Event()
    with factory() as owner:
        owner.scalar(
            select(DiagnosisWorkflowRun).where(DiagnosisWorkflowRun.id == wid).with_for_update()
        )

        def review():
            with factory() as db:
                db.execute(text("SET LOCAL statement_timeout='5s'"))
                workflow = db.get(DiagnosisWorkflowRun, wid)
                teacher = db.get(User, uid)
                teacher._actor_context = actor
                entered.set()
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

        with ThreadPoolExecutor(max_workers=1) as pool:
            pending = pool.submit(review)
            assert entered.wait(5)
            with factory() as revoker:
                revoker.execute(delete(TeachingAssignment).where(TeachingAssignment.user_id == uid))
                revoker.commit()
            owner.commit()
            pending.result(timeout=10)
    with factory() as db:
        assert db.get(DiagnosisWorkflowRun, wid).status == "waiting_teacher"
        assert db.scalar(select(func.count()).select_from(DiagnosisWorkflowReview)) == 0


def test_authorized_write_blocks_revocation_until_short_commit(migration_db):
    engine, migrate = migration_db
    migrate("upgrade", "head")
    factory = sessionmaker(engine, expire_on_commit=False)
    graph, settings, wid, uid, actor = seed(factory)
    with factory() as writer:
        workflow = writer.scalar(
            select(DiagnosisWorkflowRun).where(DiagnosisWorkflowRun.id == wid).with_for_update()
        )
        authorize_workflow_review(writer, actor, workflow)
        with factory() as revoker:
            revoker.execute(text("SET LOCAL lock_timeout='100ms'"))
            with pytest.raises(OperationalError) as failure:
                revoker.execute(delete(TeachingAssignment).where(TeachingAssignment.user_id == uid))
            assert failure.value.orig.sqlstate == "55P03"
            revoker.rollback()
        teacher = writer.get(User, uid)
        teacher._actor_context = actor
        review_workflow(
            writer,
            graph,
            workflow,
            teacher,
            settings,
            DiagnosisWorkflowReviewRequest(action="reject"),
        )
    with factory() as revoker:
        revoker.execute(delete(TeachingAssignment).where(TeachingAssignment.user_id == uid))
        revoker.commit()
    with factory() as db:
        assert db.get(DiagnosisWorkflowRun, wid).status == "rejected"
        assert db.scalar(select(func.count()).select_from(DiagnosisWorkflowReview)) == 1
        with pytest.raises(AuthorizationDenied):
            authorize_workflow_review(db, actor, db.get(DiagnosisWorkflowRun, wid))
