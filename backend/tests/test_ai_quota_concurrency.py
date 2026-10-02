from __future__ import annotations

import multiprocessing
import os
import queue
from datetime import datetime, timezone
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.ai.clients import AICompletion
from app.ai.governance import AIQuotaDenied, GovernedAIInvocation
from app.ai.reasoning import reason_about_causes
from app.core.config import Settings
from app.db.base import Base
from app.models import AICallRecord, Device, DiagnosisEpisode, DiagnosisResult
from app.models.ai_usage_reservation import AIUsageReservation


def _engine(url: str, schema: str | None):
    engine = create_engine(url)
    if schema:
        engine = engine.execution_options(schema_translate_map={None: schema})
    return engine


def _worker(
    url, schema, diagnosis_id, episode_id, settings_values, infer_episode, start, release, messages,
):
    """Each process owns its engine/Session and cannot share the Python quota lock."""
    engine = _engine(url, schema)

    class BlockingProvider:
        configured = True
        provider = "mock"
        model = "mock"

        def complete_json(self, **kwargs):
            messages.put(("provider_called", None))
            if not release.wait(15):
                raise RuntimeError("test did not release the mock Provider")
            return AICompletion("{}", input_tokens=1, output_tokens=1)

    try:
        with Session(engine, expire_on_commit=False) as db:
            diagnosis = db.get(DiagnosisResult, diagnosis_id)
            episode = db.get(DiagnosisEpisode, episode_id) if episode_id else None
            governor = GovernedAIInvocation(
                db, diagnosis, Settings(_env_file=None, **settings_values),
                call_stage="concurrent-test", episode=None if infer_episode else episode,
                operation_key=f"quota-independent:{os.getpid()}",
            )
            messages.put(("ready", None))
            if not start.wait(15):
                raise RuntimeError("test did not start workers")
            try:
                governor.complete_json(BlockingProvider(), system_prompt="s", user_prompt="u")
                messages.put(("succeeded", governor.attempts))
            except AIQuotaDenied as exc:
                messages.put(("denied", exc.code))
    except Exception as exc:
        messages.put(("unexpected", type(exc).__name__))
    finally:
        engine.dispose()


@pytest.fixture(
    params=["sqlite"] + (["postgresql"] if os.getenv("TEST_AI_QUOTA_POSTGRES_DSN") else [])
)
def quota_storage(request, tmp_path):
    schema = None
    admin = None
    if request.param == "sqlite":
        url = f"sqlite+pysqlite:///{tmp_path / 'quota.sqlite'}"
    else:
        url = os.environ["TEST_AI_QUOTA_POSTGRES_DSN"]
        if url.startswith("postgresql://"):
            url = url.replace("postgresql://", "postgresql+psycopg://", 1)
        schema = "quota_test_" + uuid4().hex
        admin = create_engine(url)
        with admin.begin() as connection:
            connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    engine = _engine(url, schema)
    try:
        Base.metadata.create_all(engine)
        yield url, schema, engine
    finally:
        engine.dispose()
        if admin is not None:
            with admin.begin() as connection:
                connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
            admin.dispose()


@pytest.mark.parametrize("limit", ["hourly", "episode", "episode-inferred", "daily"])
def test_last_quota_slot_allows_only_one_process(quota_storage, limit) -> None:
    url, schema, engine = quota_storage
    now = datetime.now(timezone.utc)
    with Session(engine, expire_on_commit=False) as db:
        device = Device(device_key="quota-synthetic", token_hash="synthetic")
        db.add(device)
        db.flush()
        diagnosis = DiagnosisResult(
            device_id=device.id, evaluated_at=now, ruleset_version="test", ruleset_hash="test",
            input_fingerprint="test", context_snapshot={}, is_test_data=True,
        )
        db.add(diagnosis)
        db.flush()
        episode = DiagnosisEpisode(
            device_id=device.id, primary_error_code="TEST", started_at=now, last_seen_at=now,
            latest_context_fingerprint="test", last_diagnosis_result_id=diagnosis.id,
            ai_call_count=1,
        )
        db.add(episode)
        db.flush()
        diagnosis.episode_id = episode.id
        db.add(AIUsageReservation(
            diagnosis_result_id=diagnosis.id, device_id=device.id, episode_id=episode.id,
            call_stage="prior-attempt", provider="mock", model="mock", status="succeeded",
            reserved_cost=0.002, accounted_cost=0.002, is_test_data=True,
        ))
        db.commit()
        diagnosis_id, episode_id = diagnosis.id, episode.id
    settings_values = {
        "ai_enabled": True, "ai_calls_per_device_hour": 2 if limit == "hourly" else 100,
        "ai_calls_per_episode": 2 if limit.startswith("episode") else 100,
        "ai_daily_budget": 0.004 if limit == "daily" else None,
        "ai_input_cost_per_1k_tokens": 1, "ai_output_cost_per_1k_tokens": 1,
        "ai_output_token_limit": 1,
    }
    context = multiprocessing.get_context("spawn")
    start, release, messages = context.Event(), context.Event(), context.Queue()
    processes = [context.Process(target=_worker, args=(
        url, schema, diagnosis_id, episode_id, settings_values, limit == "episode-inferred",
        start, release, messages,
    )) for _ in range(2)]
    received = []
    try:
        for process in processes:
            process.start()
        # Both Sessions intentionally cache the old episode count before either
        # reservation. A database lock must also refresh ORM identity-map state.
        ready = [messages.get(timeout=15) for _ in processes]
        assert ready == [("ready", None), ("ready", None)], ready
        start.set()
        # Keep the first Provider blocked. The loser must see its durable
        # reservation before that Provider produces a completion or usage audit.
        for _ in range(2):
            received.append(messages.get(timeout=15))
        assert sorted(item[0] for item in received) == ["denied", "provider_called"], received
        expected = {"hourly": "DEVICE_HOURLY_CALL_LIMIT", "episode": "EPISODE_CALL_LIMIT",
                    "episode-inferred": "EPISODE_CALL_LIMIT", "daily": "DAILY_BUDGET_LIMIT"}[limit]
        assert ("denied", expected) in received
        release.set()
        received.append(messages.get(timeout=15))
        assert received[-1] == ("succeeded", 1)
    except queue.Empty:
        pytest.fail(f"quota workers did not finish; messages={received}")
    finally:
        release.set()
        start.set()
        for process in processes:
            process.join(timeout=5)
            if process.is_alive():
                process.terminate()
                process.join(timeout=5)
        messages.close()
    assert all(process.exitcode == 0 for process in processes)
    with Session(engine) as db:
        assert db.scalar(select(func.count(AIUsageReservation.id))) == 2
        assert db.get(DiagnosisEpisode, episode_id).ai_call_count == 2
        spent = db.scalar(select(func.sum(AIUsageReservation.accounted_cost)))
        assert spent == pytest.approx(0.004)


def _diagnosis(db: Session) -> DiagnosisResult:
    device = Device(device_key="failure-synthetic", token_hash="synthetic")
    db.add(device)
    db.flush()
    diagnosis = DiagnosisResult(
        device_id=device.id, evaluated_at=datetime.now(timezone.utc), ruleset_version="test",
        ruleset_hash="test", input_fingerprint="test", context_snapshot={}, is_test_data=True,
    )
    db.add(diagnosis)
    db.commit()
    return diagnosis


class CountingProvider:
    configured = True
    provider = "mock"
    model = "mock"

    def __init__(self):
        self.calls = 0

    def complete_json(self, **kwargs):
        self.calls += 1
        return AICompletion(
            '{"error_type":"TEST","conclusion":"unknown","summary":"证据不足"}',
            input_tokens=1, output_tokens=1,
        )


@pytest.mark.parametrize("fail_commit", [1, 3], ids=["before-reservation", "settlement"])
def test_quota_storage_failure_denies_safely(quota_storage, monkeypatch, fail_commit) -> None:
    _, _, engine = quota_storage
    with Session(engine, expire_on_commit=False) as db:
        diagnosis = _diagnosis(db)
        settings = Settings(
            _env_file=None, ai_enabled=True, ai_input_cost_per_1k_tokens=1,
            ai_output_cost_per_1k_tokens=1, ai_output_token_limit=1,
        )
        governor = GovernedAIInvocation(db, diagnosis, settings, call_stage="fault-test")
        provider = CountingProvider()
        real_commit = db.commit
        commits = 0

        def injected_commit():
            nonlocal commits
            commits += 1
            if commits == fail_commit:
                raise SQLAlchemyError("synthetic quota storage failure")
            real_commit()

        monkeypatch.setattr(db, "commit", injected_commit)
        with pytest.raises(AIQuotaDenied) as error:
            governor.complete_json(provider, system_prompt="s", user_prompt="u")
        assert error.value.code == "AI_QUOTA_STORAGE_UNAVAILABLE"
        expected_calls = 0 if fail_commit == 1 else 1
        assert provider.calls == expected_calls
        # The caller can continue using the Session for a deterministic audit.
        assert db.scalar(select(func.count(AIUsageReservation.id))) == expected_calls
        if fail_commit == 3:
            row = db.scalar(select(AIUsageReservation))
            assert row.status == "reserved"
            assert row.accounted_cost == row.reserved_cost == pytest.approx(0.002)


@pytest.mark.parametrize("boundary", ["zero-budget", "tiny-input"])
def test_reasoning_entry_cannot_call_past_budget_or_input_limit(quota_storage, boundary) -> None:
    _, _, engine = quota_storage
    with Session(engine, expire_on_commit=False) as db:
        diagnosis = _diagnosis(db)
        evidence_id = str(uuid4())
        state = {
            "error_type": "TEST",
            "fault_tree_candidates": [{"cause_id": "cause", "name": "候选", "score": 0.5,
                                       "evidence_refs": [evidence_id]}],
            "evidence_registry": [{"id": evidence_id, "fact": "合成事实", "source": "rule",
                                   "status": "observed"}],
        }
        settings = Settings(
            _env_file=None, ai_enabled=True, ai_max_retries=0,
            ai_daily_budget=0 if boundary == "zero-budget" else None,
            ai_input_token_limit=1 if boundary == "tiny-input" else 10000,
            ai_input_cost_per_1k_tokens=1, ai_output_cost_per_1k_tokens=1,
        )
        provider = CountingProvider()
        result, mode = reason_about_causes(
            db, diagnosis, state, settings, workflow_run_id=None, ai_client=provider,
        )
        assert provider.calls == 0
        assert mode == "deterministic_fallback"
        assert result.error_type == "TEST"
        assert db.scalar(select(func.count(AIUsageReservation.id))) == 0
        assert db.scalar(select(AICallRecord)).attempt_count == 0
