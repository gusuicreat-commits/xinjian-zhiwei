from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from threading import Event
from uuid import uuid4

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.orm import sessionmaker
from test_device_protocol_v1 import _batch
from test_migration_r2 import migration_db as _migration_db

from app.models import Device, DeviceHeartbeat, DeviceLog, DiagnosisResult, SensorReading
from app.schemas.device import DeviceBatchIngestRequest
from app.services.data_scope import ScopeConflict
from app.services.device_ingest import cleanup_test_run, ingest_device_batch
from app.services.diagnosis import build_diagnosis_context, diagnose, save_diagnosis_result
from app.services.source_lifecycle import protect_context_sources

migration_db = _migration_db


def seed(factory):
    with factory() as db:
        device = Device(
            device_key="source-race", token_hash="synthetic", device_type="test-fixture"
        )
        db.add(device)
        db.commit()
        payload = _batch()
        run = str(uuid4())
        payload["testRunId"] = run
        ingest_device_batch(
            db=db,
            device=device,
            payload=DeviceBatchIngestRequest.model_validate(payload),
            expected_protocol_version="1.0",
            expected_schema_version="1",
            max_records=100,
            requests_per_minute=100,
        )
        context = build_diagnosis_context(
            db, device, evaluated_at=datetime(2026, 7, 27, 8, 0, 3, tzinfo=timezone.utc)
        )
        assert context.readings and context.logs and context.heartbeats
        return device.id, run, context


def test_reference_commits_before_cleanup_whole_run_is_retained(migration_db):
    engine, migrate = migration_db
    migrate("upgrade", "head")
    factory = sessionmaker(engine, expire_on_commit=False)
    did, run, context = seed(factory)
    started = Event()
    with factory() as writer:
        device = writer.get(Device, did)
        protect_context_sources(writer, did, context)

        def cleanup():
            with factory() as db:
                db.execute(text("SET LOCAL statement_timeout='5s'"))
                device = db.get(Device, did)
                started.set()
                with pytest.raises(ScopeConflict):
                    cleanup_test_run(db, device, run)
                db.rollback()

        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(cleanup)
            assert started.wait(5)
            save_diagnosis_result(writer, device, context, diagnose(context))
            future.result(timeout=10)
    with factory() as db:
        for model in (DeviceLog, SensorReading, DeviceHeartbeat):
            assert db.scalar(select(func.count()).select_from(model)) > 0


def test_cleanup_commits_before_frozen_input_cannot_create_dangling_result(migration_db):
    engine, migrate = migration_db
    migrate("upgrade", "head")
    factory = sessionmaker(engine, expire_on_commit=False)
    did, run, context = seed(factory)
    with factory() as cleaner:
        counts = cleanup_test_run(cleaner, cleaner.get(Device, did), run)
        assert counts["readings"] > 0 and counts["logs"] > 0 and counts["heartbeats"] > 0
        assert cleanup_test_run(cleaner, cleaner.get(Device, did), run)["requests"] == 0
    with factory() as writer:
        with pytest.raises(ScopeConflict):
            save_diagnosis_result(writer, writer.get(Device, did), context, diagnose(context))
        writer.rollback()
        assert writer.scalar(select(func.count()).select_from(DiagnosisResult)) == 0
