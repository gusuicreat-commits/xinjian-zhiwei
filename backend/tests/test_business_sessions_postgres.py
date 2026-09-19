"""Session ownership competition on PostgreSQL independent transactions."""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import sessionmaker
from test_migration_r2 import migration_db as _migration_db

from app.models import (
    Classroom,
    Course,
    Device,
    DeviceBinding,
    Enrollment,
    ExperimentAssignment,
    ExperimentSession,
    ExperimentSessionCommand,
    User,
)
from app.services.data_scope import ScopeConflict
from app.services.experiment_sessions import start_session
from app.services.rbac import assign_role, ensure_rbac_catalog

migration_db = _migration_db


def test_two_students_compete_for_one_device(migration_db):
    engine, migrate = migration_db
    migrate("upgrade", "head")
    factory = sessionmaker(engine, expire_on_commit=False)
    with factory() as db:
        roles = ensure_rbac_catalog(db)
        course = Course(code="competition", title="Test", is_test_data=True)
        device = Device(
            device_key="competition", token_hash="not-an-auth-token", device_type="test-fixture"
        )
        users = [
            User(
                username=f"student-{i}",
                display_name="Test",
                password_hash="unusable",
                is_test_data=True,
            )
            for i in range(2)
        ]
        db.add_all([course, device, *users])
        db.flush()
        classroom = Classroom(course_id=course.id, code="test", name="Test", is_test_data=True)
        db.add(classroom)
        db.flush()
        task = ExperimentAssignment(
            class_id=classroom.id, title="Test", status="published", is_test_data=True
        )
        db.add(task)
        db.flush()
        for user in users:
            assign_role(db, user, roles["student"])
            db.add(Enrollment(user_id=user.id, class_id=classroom.id))
            db.add(
                DeviceBinding(
                    device_id=device.id,
                    class_id=classroom.id,
                    student_user_id=user.id,
                    experiment_assignment_id=task.id,
                )
            )
        db.commit()
        user_ids, task_id = [u.id for u in users], task.id
    barrier = Barrier(2)

    def compete(user_id):
        with factory() as db:
            user = db.get(User, user_id)
            barrier.wait(timeout=10)
            try:
                return start_session(
                    db, user, request_id=uuid4(), device_key="competition", assignment_id=task_id
                )["id"]
            except ScopeConflict:
                db.rollback()
                return "conflict"

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(compete, user_ids))
    assert outcomes.count("conflict") == 1
    with factory() as db:
        assert db.scalar(select(func.count(ExperimentSession.id))) == 1
        assert db.scalar(select(func.count(ExperimentSessionCommand.id))) == 1
    migrate("check")
