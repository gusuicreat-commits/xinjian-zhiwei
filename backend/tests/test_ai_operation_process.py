"""Real process interruption, local HTTP only, isolated database."""

import multiprocessing
import threading
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.ai.clients import OpenAICompatibleClient
from app.ai.governance import AIQuotaDenied, GovernedAIInvocation
from app.core.config import Settings
from app.db.base import Base
from app.models import Device, DiagnosisResult
from app.models.ai_operation import AIOperation
from app.models.ai_usage_reservation import AIUsageReservation


def _settings():
    return Settings(
        _env_file=None,
        ai_enabled=True,
        ai_require_knowledge=False,
        ai_calls_per_device_hour=10,
        ai_calls_per_episode=10,
    )


def _client(url):
    return OpenAICompatibleClient(
        provider="synthetic-local",
        model="synthetic",
        base_url=url,
        api_key="synthetic",
        timeout_seconds=10,
        max_retries=0,
    )


def _worker(url, diagnosis_id, endpoint):
    with Session(create_engine(url), expire_on_commit=False) as db:
        governor = GovernedAIInvocation(
            db, db.get(DiagnosisResult, diagnosis_id), _settings(), call_stage="process-test"
        )
        governor.complete_json(_client(endpoint), system_prompt="test", user_prompt="test")


def test_kill_after_server_receives_does_not_resend(tmp_path, monkeypatch):
    monkeypatch.setenv("NO_PROXY", "127.0.0.1,localhost")
    monkeypatch.setenv("no_proxy", "127.0.0.1,localhost")
    url = f"sqlite:///{tmp_path / 'operation.sqlite'}"
    engine = create_engine(url)
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        device = Device(
            device_key="synthetic-process",
            display_name="synthetic",
            device_type="test-fixture",
            token_hash="synthetic-unused",
        )
        db.add(device)
        db.flush()
        diagnosis = DiagnosisResult(
            device_id=device.id,
            evaluated_at=datetime.now(timezone.utc),
            ruleset_version="synthetic",
            ruleset_hash="synthetic",
            input_fingerprint="synthetic",
            matched_rules=[],
            evidence=[],
            context_snapshot={},
            is_test_data=True,
        )
        db.add(diagnosis)
        db.commit()
        diagnosis_id = diagnosis.id
    received, release = threading.Event(), threading.Event()
    calls = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            self.rfile.read(int(self.headers["Content-Length"]))
            calls.append(1)
            received.set()
            release.wait(10)
            self.close_connection = True

        def log_message(self, *_):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    endpoint = f"http://127.0.0.1:{server.server_port}"
    process = multiprocessing.get_context("spawn").Process(
        target=_worker, args=(url, diagnosis_id, endpoint)
    )
    try:
        process.start()
        assert received.wait(10), "child must reach real local HTTP before interruption"
        process.terminate()
        process.join(5)
        assert not process.is_alive()
        with Session(engine, expire_on_commit=False) as db:
            assert db.scalar(select(AIOperation)).status == "dispatching"
            assert db.scalar(select(AIUsageReservation)).status == "reserved"
            governor = GovernedAIInvocation(
                db, db.get(DiagnosisResult, diagnosis_id), _settings(), call_stage="process-test"
            )
            with pytest.raises(AIQuotaDenied, match="AI_OUTCOME_UNKNOWN"):
                governor.complete_json(_client(endpoint), system_prompt="test", user_prompt="test")
            assert len(list(db.scalars(select(AIUsageReservation)))) == 1
            assert len(calls) == 1
    finally:
        release.set()
        if process.is_alive():
            process.terminate()
            process.join(5)
        server.shutdown()
        server.server_close()
        thread.join(5)
        engine.dispose()
