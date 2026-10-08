"""Two processes competing for one logical operation on isolated PostgreSQL."""

import multiprocessing
from datetime import datetime, timezone

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from test_migration_r2 import migration_db as migration_db

from app.ai.clients import AICompletion
from app.ai.governance import AIQuotaDenied, GovernedAIInvocation
from app.core.config import Settings
from app.models import Device, DiagnosisResult
from app.models.ai_operation import AIOperation
from app.models.ai_usage_reservation import AIUsageReservation
from app.models.classroom import AuditEvent


def _audit_replayed_denial(url, diagnosis_id, release, messages):
    class NoNewCall:
        provider, model, configured = "synthetic", "synthetic", True

        def complete_json(self, **_):
            raise AssertionError("completed operation must not call Provider again")

    engine = create_engine(url)
    try:
        with Session(engine, expire_on_commit=False) as db:
            governor = GovernedAIInvocation(
                db, db.get(DiagnosisResult, diagnosis_id),
                Settings(_env_file=None, ai_enabled=True), call_stage="pg-denial-audit",
            )
            governor.complete_json(NoNewCall(), system_prompt="test", user_prompt="test")
            messages.put("ready")
            assert release.wait(10)
            messages.put(governor.audit_delivery_denial("AI_DELIVERY_ACCESS_REVOKED"))
    finally:
        engine.dispose()


def test_concurrent_replayed_denials_have_one_event_and_no_new_usage(migration_db):  # noqa: F811
    engine, migrate = migration_db
    migrate("upgrade", "head")
    class Client:
        provider, model, configured = "synthetic", "synthetic", True

        def complete_json(self, **_):
            return AICompletion(content="{}", input_tokens=1, output_tokens=1)

    with Session(engine, expire_on_commit=False) as db:
        device = Device(device_key="synthetic-audit", token_hash="synthetic")
        db.add(device)
        db.flush()
        diagnosis = DiagnosisResult(
            device_id=device.id, evaluated_at=datetime.now(timezone.utc),
            ruleset_version="test", ruleset_hash="test", input_fingerprint="test",
            matched_rules=[], evidence=[], context_snapshot={}, is_test_data=True,
        )
        db.add(diagnosis)
        db.commit()
        governor = GovernedAIInvocation(db, diagnosis, Settings(_env_file=None, ai_enabled=True),
                                        call_stage="pg-denial-audit")
        governor.complete_json(Client(), system_prompt="test", user_prompt="test")
        diagnosis_id = diagnosis.id
    context = multiprocessing.get_context("spawn")
    release, messages = context.Event(), context.Queue()
    args = (engine.url.render_as_string(hide_password=False), diagnosis_id, release, messages)
    processes = [context.Process(target=_audit_replayed_denial, args=args) for _ in range(2)]
    try:
        for process in processes:
            process.start()
        assert [messages.get(timeout=10) for _ in processes] == ["ready", "ready"]
        release.set()
        assert [messages.get(timeout=10) for _ in processes] == [True, True]
        for process in processes:
            process.join(10)
            assert process.exitcode == 0
        with Session(engine) as db:
            assert len(list(db.scalars(select(AuditEvent).where(
                AuditEvent.action == "ai.delivery_denied")))) == 1
            assert len(list(db.scalars(select(AIUsageReservation)))) == 1
            assert db.scalar(select(AIOperation)).attempt_no == 1
    finally:
        release.set()
        for process in processes:
            if process.is_alive():
                process.terminate()
                process.join(5)


def _compete(url, diagnosis_id, ready, release, messages):
    class Client:
        provider, model, configured = "synthetic", "synthetic", True

        def complete_json(self, **_):
            messages.put("physical_request")
            ready.set()
            assert release.wait(10)
            return AICompletion(content="{}", input_tokens=1, output_tokens=1)

    engine = create_engine(url)
    try:
        with Session(engine, expire_on_commit=False) as db:
            governor = GovernedAIInvocation(
                db,
                db.get(DiagnosisResult, diagnosis_id),
                Settings(_env_file=None, ai_enabled=True),
                call_stage="pg-competition",
            )
            try:
                governor.complete_json(Client(), system_prompt="test", user_prompt="test")
                messages.put("succeeded")
            except AIQuotaDenied as exc:
                messages.put(exc.code)
    finally:
        engine.dispose()


def test_two_processes_send_only_once(migration_db):  # noqa: F811
    engine, migrate = migration_db
    migrate("upgrade", "head")
    with Session(engine) as db:
        device = Device(device_key="synthetic-competition", token_hash="synthetic")
        db.add(device)
        db.flush()
        diagnosis = DiagnosisResult(
            device_id=device.id,
            evaluated_at=datetime.now(timezone.utc),
            ruleset_version="test",
            ruleset_hash="test",
            input_fingerprint="test",
            matched_rules=[],
            evidence=[],
            context_snapshot={},
            is_test_data=True,
        )
        db.add(diagnosis)
        db.commit()
        diagnosis_id = diagnosis.id
    context = multiprocessing.get_context("spawn")
    ready, release, messages = context.Event(), context.Event(), context.Queue()
    args = (
        engine.url.render_as_string(hide_password=False),
        diagnosis_id,
        ready,
        release,
        messages,
    )
    processes = [context.Process(target=_compete, args=args) for _ in range(2)]
    try:
        processes[0].start()
        assert ready.wait(10)
        assert messages.get(timeout=5) == "physical_request"
        processes[1].start()
        assert messages.get(timeout=10) == "AI_OUTCOME_UNKNOWN"
        release.set()
        assert messages.get(timeout=10) == "succeeded"
        for process in processes:
            process.join(10)
            assert process.exitcode == 0
        with Session(engine) as db:
            assert len(list(db.scalars(select(AIUsageReservation)))) == 1
            assert db.scalar(select(AIOperation)).attempt_no == 1
            assert db.scalar(select(AIOperation)).status == "succeeded"
    finally:
        release.set()
        for process in processes:
            if process.is_alive():
                process.terminate()
                process.join(5)
