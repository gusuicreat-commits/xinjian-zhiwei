"""Real PostgreSQL serialization and non-destructive migration coverage."""

from concurrent.futures import ThreadPoolExecutor
from threading import Event
from uuid import uuid4

import pytest
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.models import Device, DiagnosisResult, KnowledgeCase, MemoryEvent, User
from app.models.base import utc_now
from app.services.memory import case_source, current_source, record_uses, register_stop

pytest_plugins = ["test_migration_r2"]


@pytest.fixture
def memory_pg(migration_db):
    engine, migrate = migration_db
    migrate("upgrade", "head")
    with Session(engine, expire_on_commit=False) as db:
        actor = User(
            username="memory-pg-" + uuid4().hex,
            display_name="合成管理员",
            password_hash="unused",
            is_test_data=True,
        )
        device = Device(
            device_key="memory-pg-" + uuid4().hex,
            display_name="合成设备",
            device_type="test-fixture",
            token_hash="unused",
        )
        case = KnowledgeCase(
            id="memory-test-case",
            experiment_type="synthetic",
            error_type="synthetic",
            symptom="合成案例",
            source_ref="test://memory",
            version="1",
            root_cause_status="confirmed",
            facts_locked=True,
            quality_check_passed=True,
            review_status="approved",
            is_test_data=True,
        )
        db.add_all([actor, device, case])
        db.flush()
        diagnosis = DiagnosisResult(
            device_id=device.id,
            evaluated_at=utc_now(),
            ruleset_version="test",
            ruleset_hash="0" * 64,
            input_fingerprint="1" * 64,
            matched_rules=[],
            evidence=[],
            context_snapshot={},
            is_test_data=True,
        )
        db.add(diagnosis)
        db.commit()
        yield engine, actor.id, diagnosis.id, case.id, case_source(case)


def test_source_delivery_waits_for_withdrawal_then_rechecks(memory_pg):
    engine, actor_id, _, case_id, source = memory_pg
    started = Event()
    with Session(engine) as writer, ThreadPoolExecutor(max_workers=1) as pool:
        case = writer.scalar(
            select(KnowledgeCase).where(KnowledgeCase.id == case_id).with_for_update()
        )
        case.review_status = "withdrawn"
        register_stop(writer, source, writer.get(User, actor_id), "synthetic withdrawal")
        writer.flush()

        def reader():
            with Session(engine) as db:
                # Ensures a missing lock cannot accidentally pass by scheduling after commit.
                db.execute(text("SET lock_timeout='200ms'"))
                started.set()
                return current_source(db, source, is_test_data=True)

        waiting = pool.submit(reader)
        assert started.wait(2)
        with pytest.raises(Exception) as caught:
            waiting.result(timeout=3)
        assert "lock timeout" in str(caught.value)
        writer.commit()
    with Session(engine) as db:
        assert not current_source(db, source, is_test_data=True)
        assert db.query(MemoryEvent).count() == 1


def test_concurrent_relationship_writes_are_unique(memory_pg):
    engine, _, diagnosis_id, case_id, _ = memory_pg

    def insert():
        with Session(engine) as db:
            record_uses(
                db,
                db.get(DiagnosisResult, diagnosis_id),
                [{"chunk_id": case_id, "source_version": "1"}],
                target_type="workflow",
                target_id="synthetic-target",
                use_kind="matched",
            )
            db.commit()

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(insert) for _ in range(2)]
        for future in futures:
            future.result(timeout=5)
    with engine.connect() as conn:
        assert conn.scalar(text("SELECT count(*) FROM memory_uses")) == 1


def test_governance_migration_preserves_history_and_refuses_nonempty_downgrade(memory_pg):
    engine, actor_id, _, _, source = memory_pg
    from importlib.util import module_from_spec, spec_from_file_location
    from pathlib import Path
    from unittest.mock import patch

    path = Path(__file__).parents[1] / "migrations/versions/20260927_0035_memory_lifecycle.py"
    spec = spec_from_file_location("memory_migration", path)
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    with Session(engine) as db:
        register_stop(db, source, db.get(User, actor_id), "retain audit")
        db.commit()
    with engine.begin() as conn, patch.object(module.op, "get_bind", return_value=conn):
        with pytest.raises(RuntimeError, match="must not be destroyed"):
            module.downgrade()
        assert conn.scalar(text("SELECT count(*) FROM diagnosis_results")) == 1
        assert conn.scalar(text("SELECT count(*) FROM memory_events")) == 1
