import os
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from threading import Barrier
from uuid import uuid4

import pytest
from shared_source_fixture import persist_context_fixture
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session

from app.db.base import Base
from app.diagnosis.schemas import ContextLog, DiagnosisContext
from app.models import Device, DiagnosisEpisode, DiagnosisResult, GuidanceHistory
from app.services.diagnosis import diagnose, save_diagnosis_result
from app.services.guidance import _build_guidance_records as generate_guidance

POSTGRES_DSN = os.getenv("XINJIAN_EVAL_POSTGRES_DSN") or os.getenv("TEST_EPISODE_POSTGRES_DSN")


@pytest.fixture(params=["sqlite"] + (["postgresql"] if POSTGRES_DSN else []))
def lifecycle_storage(request, tmp_path):
    schema = None
    if request.param == "postgresql":
        engine = create_engine(POSTGRES_DSN.replace("postgresql://", "postgresql+psycopg://", 1))
        schema = "episode_r2_" + uuid4().hex
        with engine.begin() as conn:
            conn.execute(text(f'CREATE SCHEMA "{schema}"'))
        scoped = engine.execution_options(schema_translate_map={None: schema})
    else:
        engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'episode.sqlite'}")
        scoped = engine
    Base.metadata.create_all(scoped)
    try:
        yield scoped
    finally:
        if schema:
            with engine.begin() as conn:
                conn.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        engine.dispose()


@pytest.mark.parametrize("distinct", [False, True])
def test_parallel_diagnoses_count_new_related_evidence_once(lifecycle_storage, distinct):
    engine = lifecycle_storage
    now = datetime.now(timezone.utc)
    ids = []
    with Session(engine) as db:
        device = Device(device_key="r2-concurrent", token_hash="synthetic")
        db.add(device)
        db.flush()
        device_id = device.id
        for i in range(2):
            context = DiagnosisContext(
                device_id=device.device_key,
                evaluated_at=now,
                last_seen_at=now,
                logs=[
                    ContextLog(
                        id=f"failure-{i if distinct else 0}",
                        level="ERROR",
                        event_code="SENSOR_READ_FAILED",
                        message="synthetic",
                        occurred_at=now,
                        is_test_data=True,
                    )
                ],
            )
            persist_context_fixture(db, device, context)
            result = save_diagnosis_result(db, device, context, diagnose(context))
            ids.append(result.id)
    barrier = Barrier(2)

    def worker(diagnosis_id):
        with Session(engine, expire_on_commit=False) as db:
            device = db.get(Device, device_id)
            diagnosis = db.get(DiagnosisResult, diagnosis_id)
            barrier.wait(timeout=10)
            return generate_guidance(db, device, diagnosis)[0].failure_count

    with ThreadPoolExecutor(max_workers=2) as pool:
        counts = list(pool.map(worker, ids))
    with Session(engine) as db:
        episodes = list(db.scalars(select(DiagnosisEpisode)))
        assert len(episodes) == 1
        assert episodes[0].failure_count == episodes[0].evidence_revision == (2 if distinct else 1)
        assert sorted(counts) == ([1, 2] if distinct else [1, 1])
        assert len(list(db.scalars(select(GuidanceHistory)))) == 2


def test_older_snapshot_registered_late_cannot_resolve_unseen_evidence(lifecycle_storage):
    from datetime import timedelta
    from types import SimpleNamespace

    from app.services.diagnosis_episode import EpisodeFeedbackConflict, apply_episode_feedback

    engine = lifecycle_storage
    now = datetime.now(timezone.utc)
    with Session(engine, expire_on_commit=False) as db:
        device = Device(device_key="r2-delayed", token_hash="synthetic")
        db.add(device)
        db.flush()
        records = []
        for index in range(2):
            context = DiagnosisContext(
                device_id=device.device_key,
                evaluated_at=now + timedelta(seconds=index),
                last_seen_at=now,
                logs=[
                    ContextLog(
                        id=f"failure-{index}",
                        level="ERROR",
                        event_code="SENSOR_READ_FAILED",
                        message="synthetic",
                        occurred_at=now,
                        is_test_data=True,
                    )
                ],
            )
            persist_context_fixture(db, device, context)
            records.append(save_diagnosis_result(db, device, context, diagnose(context)))
        assert generate_guidance(db, device, records[1])[0].failure_count == 1
        assert generate_guidance(db, device, records[0])[0].failure_count == 2
        assert records[0].episode_id == records[1].episode_id
        assert records[0].episode_evidence_revision is None
        with pytest.raises(EpisodeFeedbackConflict):
            apply_episode_feedback(db, records[0], SimpleNamespace(action="resolved"))


def test_new_evidence_racing_resolution_has_one_lifecycle_order(lifecycle_storage):
    from datetime import timedelta
    from types import SimpleNamespace

    from app.services.diagnosis_episode import (
        EpisodeFeedbackConflict,
        apply_episode_feedback,
        lifecycle_lock,
    )

    engine = lifecycle_storage
    now = datetime.now(timezone.utc)
    with Session(engine, expire_on_commit=False) as db:
        device = Device(device_key="r2-feedback-race", token_hash="synthetic")
        db.add(device)
        db.flush()
        device_id = device.id
        records = []
        for index in range(2):
            context = DiagnosisContext(
                device_id=device.device_key,
                evaluated_at=now + timedelta(seconds=index),
                last_seen_at=now,
                logs=[
                    ContextLog(
                        id=f"failure-{j}",
                        level="ERROR",
                        event_code="SENSOR_READ_FAILED",
                        message="synthetic",
                        occurred_at=now,
                        is_test_data=True,
                    )
                    for j in range(index + 1)
                ],
            )
            persist_context_fixture(db, device, context)
            records.append(save_diagnosis_result(db, device, context, diagnose(context)))
        generate_guidance(db, device, records[0])
        first_id, second_id = [item.id for item in records]
        first_episode = records[0].episode_id
    barrier = Barrier(2)

    def register():
        with Session(engine, expire_on_commit=False) as db:
            result = db.get(DiagnosisResult, second_id)
            device = db.get(Device, device_id)
            barrier.wait(timeout=10)
            generate_guidance(db, device, result)
            return result.episode_id

    def resolve():
        with Session(engine, expire_on_commit=False) as db:
            result = db.get(DiagnosisResult, first_id)
            barrier.wait(timeout=10)
            try:
                with lifecycle_lock(db, result):
                    apply_episode_feedback(db, result, SimpleNamespace(action="resolved"))
                    db.commit()
                return "resolved"
            except EpisodeFeedbackConflict:
                db.rollback()
                return "conflict"

    with ThreadPoolExecutor(max_workers=2) as pool:
        registration = pool.submit(register)
        resolution = pool.submit(resolve)
        second_episode, outcome = registration.result(timeout=15), resolution.result(timeout=15)
    with Session(engine) as db:
        old = db.get(DiagnosisEpisode, first_episode)
        current = db.get(DiagnosisEpisode, second_episode)
        if outcome == "resolved":
            assert old.status == "resolved"
            # Both samples predate closure: delivery after closure is history,
            # not a new period of physical failure.
            assert current.id == old.id
            assert current.failure_count == 1
        else:
            assert current.id == old.id
            assert current.status == "open"
            assert current.failure_count == current.evidence_revision == 2
