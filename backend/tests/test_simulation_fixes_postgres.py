from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import uuid4

import pytest
from shared_authorization import session_actor_fixture
from sqlalchemy import MetaData, Table, select, text
from sqlalchemy.orm import sessionmaker
from test_device_protocol_v1 import _batch
from test_migration_r2 import _seed
from test_migration_r2 import migration_db as _migration_db

from app.models import (
    AuditEvent,
    Device,
    DeviceHeartbeat,
    DeviceLog,
    ExperimentSession,
    ExperimentSessionCommand,
    IngestionRequest,
    SensorReading,
    User,
)
from app.schemas.device import DeviceBatchIngestRequest
from app.services.data_scope import ScopeConflict
from app.services.device_ingest import ingest_device_batch
from app.services.experiment_sessions import end_session, release_session, start_session
from app.services.rbac import assign_role, ensure_rbac_catalog

migration_db = _migration_db


def test_counter_upgrade_preserves_rows_and_ingests_full_large_batch(migration_db):
    engine, migrate = migration_db
    migrate("upgrade", "20260919_0031")
    originals = {}
    with engine.begin() as conn:
        device = _seed(conn, "devices", device_key="large-counter-test")
        for name in ("ingestion_requests", "device_heartbeats", "device_logs", "sensor_readings"):
            originals[name] = _seed(
                conn, name, device_id=device["id"], sequence_no=2147483647, uptime_ms=2147483647
            )
    migrate("upgrade", "20260930_0036")
    with engine.connect() as conn:
        for name, old in originals.items():
            table = Table(name, MetaData(), autoload_with=conn)
            assert (
                dict(conn.execute(table.select().where(table.c.id == old["id"])).mappings().one())
                == old
            )
    factory = sessionmaker(engine)
    for value in (2**31, 2**32 - 1, 2**53 - 1):
        payload = _batch(boot_id=str(uuid4()), sequence_no=value)
        payload["uptimeMs"] = value
        with factory() as db:
            d = db.get(Device, device["id"])
            for replay in (False, True):
                response = ingest_device_batch(
                    db=db,
                    device=d,
                    payload=DeviceBatchIngestRequest.model_validate(payload),
                    expected_protocol_version="1.0",
                    expected_schema_version="1",
                    max_records=100,
                    requests_per_minute=100,
                )
                assert response.idempotent_replay == replay
            for model in (IngestionRequest, DeviceHeartbeat, DeviceLog, SensorReading):
                row = db.scalars(select(model).where(model.boot_id == payload["bootId"])).one()
                assert row.sequence_no == row.uptime_ms == value
    # A destructive narrowing must be refused before any table is changed.
    with pytest.raises(AssertionError, match="Cannot narrow protocol counters"):
        migrate("downgrade", "20260919_0031")
    with engine.connect() as conn:
        assert conn.scalar(text("SELECT version_num FROM alembic_version")) == "20260930_0036"
    migrate("upgrade", "head")
    migrate("check")


@pytest.mark.parametrize("competitor", ["teacher", "student", "next_student"])
def test_release_competes_on_same_device_without_closing_new_session(migration_db, competitor):
    engine, migrate = migration_db
    migrate("upgrade", "head")
    with engine.begin() as conn:
        course = _seed(conn, "courses")
        classroom = _seed(conn, "classes", course_id=course["id"])
        task = _seed(
            conn,
            "experiment_assignments",
            class_id=classroom["id"],
            status="published",
            is_test_data=True,
        )
        device = _seed(conn, "devices", device_key="handover", device_type="test-fixture")
        students = [_seed(conn, "users") for _ in range(2)]
        teachers = [_seed(conn, "users") for _ in range(2)]
        for student in students:
            _seed(
                conn,
                "enrollments",
                class_id=classroom["id"],
                user_id=student["id"],
                status="active",
            )
            _seed(
                conn,
                "device_bindings",
                class_id=classroom["id"],
                device_id=device["id"],
                student_user_id=student["id"],
                experiment_assignment_id=task["id"],
                is_active=True,
            )
        for teacher in teachers:
            _seed(conn, "teaching_assignments", class_id=classroom["id"], user_id=teacher["id"])
        old = _seed(
            conn,
            "experiment_sessions",
            device_id=device["id"],
            student_user_id=students[0]["id"],
            experiment_assignment_id=task["id"],
            status="active",
            version_no=1,
        )
    factory = sessionmaker(engine, expire_on_commit=False)
    with factory() as db:
        roles = ensure_rbac_catalog(db)
        for record in students:
            assign_role(db, db.get(User, record["id"]), roles["student"])
        for record in teachers:
            assign_role(db, db.get(User, record["id"]), roles["teacher"])
        db.commit()
    gate = Barrier(2)

    def run(which):
        with factory() as db:
            actor = (
                teachers[which]
                if which == 0 or competitor == "teacher"
                else students[0 if competitor == "student" else 1]
            )
            user = session_actor_fixture(db, db.get(User, actor["id"]))
            gate.wait(timeout=10)
            try:
                if which == 1 and competitor == "student":
                    return end_session(
                        db,
                        user,
                        session_id=old["id"],
                        request_id=uuid4(),
                        expected_version=1,
                        reason="completed",
                    )
                if which == 1 and competitor == "next_student":
                    return start_session(
                        db,
                        user,
                        request_id=uuid4(),
                        device_key="handover",
                        assignment_id=task["id"],
                    )
                return release_session(
                    db,
                    user,
                    session_id=old["id"],
                    request_id=uuid4(),
                    expected_version=1,
                    reason="交接",
                )
            except ScopeConflict:
                db.rollback()
                return "conflict"

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(run, range(2)))
    if competitor != "next_student":
        assert outcomes.count("conflict") == 1
    with factory() as db:
        assert db.get(ExperimentSession, old["id"]).version_no == 2
        if competitor == "next_student":
            if outcomes[1] == "conflict":
                start_session(
                    db,
                    session_actor_fixture(db, db.get(User, students[1]["id"])),
                    request_id=uuid4(),
                    device_key="handover",
                    assignment_id=task["id"],
                )
            active = list(
                db.scalars(select(ExperimentSession).where(ExperimentSession.status == "active"))
            )
            assert len(active) == 1 and active[0].student_user_id == students[1]["id"]
        assert (
            len(list(db.scalars(select(AuditEvent).where(AuditEvent.resource_id == old["id"]))))
            == 1
        )
        assert (
            len(
                list(
                    db.scalars(
                        select(ExperimentSessionCommand).where(
                            ExperimentSessionCommand.session_id == old["id"]
                        )
                    )
                )
            )
            == 1
        )
