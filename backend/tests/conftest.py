from collections.abc import Generator
from datetime import datetime, timezone
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.security import hash_device_token, hash_password
from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.models import (
    Classroom,
    Course,
    Device,
    ExperimentAssignment,
    ExperimentSession,
    User,
)

TEST_DEVICE_ID = "phase2-test-device"
TEST_DEVICE_TOKEN = "phase2-test-token-not-for-production"


@pytest.fixture
def api_context() -> Generator[dict[str, Any], None, None]:
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    testing_session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    Base.metadata.create_all(engine)

    with testing_session() as db:
        device = Device(
            device_key=TEST_DEVICE_ID,
            display_name="明确标记的 Phase 2 测试设备",
            device_type="test-fixture",
            token_hash=hash_device_token(TEST_DEVICE_TOKEN, iterations=1_000),
        )
        student = User(
            username="phase2-test-student",
            display_name="Phase 2 合成学生",
            password_hash=hash_password("synthetic-password", iterations=1_000),
            is_test_data=True,
        )
        course = Course(
            code="phase2-test-course",
            title="Phase 2 合成课程",
            is_test_data=True,
        )
        db.add_all([device, student, course])
        db.flush()
        classroom = Classroom(
            course_id=course.id,
            code="phase2-test-class",
            name="Phase 2 合成班级",
            is_test_data=True,
        )
        db.add(classroom)
        db.flush()
        assignment = ExperimentAssignment(
            class_id=classroom.id,
            title="Phase 2 合成实验",
            status="published",
            is_test_data=True,
        )
        db.add(assignment)
        db.flush()
        experiment_session = ExperimentSession(
            experiment_assignment_id=assignment.id,
            student_user_id=student.id,
            device_id=device.id,
            status="active",
            started_at=datetime.now(timezone.utc),
            is_test_data=True,
        )
        db.add(experiment_session)
        db.commit()
        experiment_session_id = experiment_session.id

    def override_get_db() -> Generator[Session, None, None]:
        with testing_session() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as client:
        yield {
            "client": client,
            "session_factory": testing_session,
            "headers": {
                "X-Device-ID": TEST_DEVICE_ID,
                "X-Device-Token": TEST_DEVICE_TOKEN,
                "X-Experiment-Session-ID": experiment_session_id,
            },
            "experiment_session_id": experiment_session_id,
        }
    app.dependency_overrides.clear()
    Base.metadata.drop_all(engine)
    engine.dispose()
