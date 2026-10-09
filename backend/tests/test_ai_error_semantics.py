"""XJ-014 fixed behavioral oracle, captured on HEAD d36e1c0 before classification.

No expected status, amount or retry decision is computed by the governor.
PostgreSQL failures execute real failing SQL in a disposable migrated schema.
"""

import json
import time
from datetime import datetime, timezone

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pipeline import diagnose_device
from sqlalchemy import event, select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session
from test_ai_transport_lifecycle import BytesStream
from test_business_error_classification import (
    test_business_boundary_classifies_and_rolls_back as assert_business_boundary,
)
from test_knowledge_case_drafting import FakePolishClient
from test_knowledge_case_drafting import persisted_draft as persisted_draft
from test_migration_r2 import migration_db as migration_db
from test_query_tasks import api_context as postgres_api_context

from app.ai.clients import (
    AIProviderError,
    OpenAICompatibleClient,
    ProviderOutcomeUnknown,
    ProviderRequestRejected,
    ProviderTemporaryFailure,
    classified_provider_error,
)
from app.ai.governance import (
    AIInputRejected,
    AIOutcomeUnknown,
    AIQuotaDenied,
    AIQuotaRejected,
    AIResultStale,
    AIScopeRejected,
    AIStorageUnavailable,
    GovernedAIInvocation,
    current_delivery_scope,
)
from app.api.errors import register_error_handlers
from app.api.v1.routes import knowledge
from app.core.config import Settings
from app.core.errors import (
    AccessDenied,
    ConflictError,
    InvalidRequest,
    StaleError,
    TemporarilyUnavailable,
)
from app.models import Device, DiagnosisResult, User
from app.models.ai_operation import AIOperation
from app.models.ai_usage_reservation import AIUsageReservation
from app.services.auth import AuthorizationDenied

boundary_context = postgres_api_context


def settings(**overrides):
    return Settings(_env_file=None, **{
        "ai_enabled": True, "ai_max_retries": 1, "ai_total_timeout_seconds": 10,
        "ai_output_token_limit": 10, "ai_calls_per_device_hour": 20,
        "ai_input_cost_per_1k_tokens": 1, "ai_output_cost_per_1k_tokens": 2,
        **overrides,
    })


def transport(monkeypatch, failure):
    calls = []

    async def handle(request):
        calls.append(time.monotonic())
        if len(calls) == 1:
            if failure == "unknown":
                raise httpx.ReadError("synthetic connection interrupted before response")
            if failure == "connect":
                raise httpx.ConnectError("synthetic not connected")
            if failure in {"400", "429", "500"}:
                return httpx.Response(int(failure), headers={"Retry-After": "0.05"})
        return httpx.Response(200, stream=BytesStream(json.dumps({
            "choices": [{"message": {"content": "{}"}}],
            "usage": {"prompt_tokens": 100, "completion_tokens": 50},
        }).encode()))

    original = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: original(
        transport=httpx.MockTransport(handle), **kw,
    ))
    client = OpenAICompatibleClient(
        provider="synthetic", model="synthetic", base_url="https://synthetic.invalid",
        api_key="unused", timeout_seconds=5, max_retries=1,
    )
    return client, calls


# (calls, operation status, retry_allowed, reservation status/charged amount).
# s+u = 1 estimated token; reserve 1/1000*1 + 10/1000*2 = .021.
# Returned usage 100/1000*1 + 50/1000*2 = .2.
ORACLE = {
    "quota": (0, None, False, []),
    "reserve_db": (0, None, False, []),
    "scope_db": (0, None, False, []),
    "400": (1, "failed_known", False, [("failed", .021)]),
    "429": (2, "succeeded", False, [("failed", .021), ("succeeded", .2)]),
    "connect": (2, "succeeded", False, [("failed", .021), ("succeeded", .2)]),
    "unknown": (1, "outcome_unknown", False, [("failed", .021)]),
    "500": (1, "outcome_unknown", False, [("failed", .021)]),
    "settle_db": (1, "dispatching", False, [("reserved", .021)]),
    "revoked": (1, "succeeded", False, [("succeeded", .2)]),
}


@pytest.mark.parametrize("failure", list(ORACLE))
def test_head_oracle_postgres_dispatch_and_accounting(migration_db, monkeypatch, failure):  # noqa: F811
    engine, migrate = migration_db
    migrate("upgrade", "head")
    client, calls = transport(monkeypatch, failure)
    config = settings(**({"ai_daily_budget": 0} if failure == "quota" else {}))
    with Session(engine, expire_on_commit=False) as db:
        device = Device(device_key="xj014", token_hash="synthetic")
        db.add(device)
        db.flush()
        diagnosis = diagnose_device(db, device)
        diagnosis.is_test_data = True
        db.commit()
        diagnosis_id = diagnosis.id
        governor = GovernedAIInvocation(db, diagnosis, config, call_stage="xj014")
        armed = True

        def fail_commit(session):
            nonlocal armed
            reserve = any(isinstance(x, AIUsageReservation) for x in session.new)
            settle = any(isinstance(x, AIUsageReservation) for x in session.dirty)
            if armed and ((failure == "reserve_db" and reserve)
                          or (failure == "settle_db" and settle)):
                armed = False
                session.execute(text("SELECT 1/0"))

        event.listen(db, "before_commit", fail_commit)
        if failure == "scope_db":
            original_refresh = db.refresh

            def fail_scope(*args, **kwargs):
                nonlocal armed
                if armed:
                    armed = False
                    db.execute(text("SELECT 1/0"))
                return original_refresh(*args, **kwargs)

            monkeypatch.setattr(db, "refresh", fail_scope)
        if failure == "revoked":
            def recheck():
                if calls:
                    raise AuthorizationDenied(403)
            governor.recheck_access = recheck
        with pytest.raises((AIProviderError, AuthorizationDenied)) as caught:
            governor.complete_json(client, system_prompt="s", user_prompt="u")
        # New type contract is independent of the unchanged HEAD behavior oracle.
        assert isinstance(caught.value, {
            "quota": AIQuotaRejected, "reserve_db": AIStorageUnavailable,
            "scope_db": AIStorageUnavailable, "400": ProviderRequestRejected,
            "429": ProviderTemporaryFailure, "connect": ProviderTemporaryFailure,
            "unknown": ProviderOutcomeUnknown, "500": ProviderOutcomeUnknown,
            "settle_db": AIStorageUnavailable, "revoked": AuthorizationDenied,
        }[failure])
        if failure in {"429", "connect"}:
            assert governor.operation.status == "failed_known"
            assert governor.operation.retry_allowed is True
            assert governor.retry(caught.value) is True
            governor.complete_json(client, system_prompt="s", user_prompt="u")
            assert calls[1] - calls[0] >= (.05 if failure == "429" else .25)
        elif failure != "revoked":
            assert governor.retry(caught.value) is False
        event.remove(db, "before_commit", fail_commit)
        db.rollback()
    # New connection/session: saved states and amounts survive invocation recovery.
    with Session(engine, expire_on_commit=False) as db:
        operation = db.scalar(select(AIOperation))
        rows = list(db.scalars(select(AIUsageReservation).order_by(AIUsageReservation.attempt_no)))
        count, status, retry_allowed, charges = ORACLE[failure]
        assert len(calls) == count
        assert (operation.status if operation else None) == status
        assert (operation.retry_allowed if operation else False) is retry_allowed
        assert [(r.status, r.accounted_cost) for r in rows] == charges
        assert [r.reserved_cost for r in rows] == [.021] * count
        assert [r.attempt_no for r in rows] == list(range(1, count + 1))
        if operation:
            assert operation.attempt_no == count
            assert all(r.operation_id == operation.id for r in rows)
        if failure in {"unknown", "500", "settle_db", "400"}:
            recovered = GovernedAIInvocation(
                db, db.get(DiagnosisResult, diagnosis_id), config, call_stage="xj014",
            )
            with pytest.raises(AIQuotaDenied) as recovered_error:
                recovered.complete_json(client, system_prompt="s", user_prompt="u")
            assert isinstance(recovered_error.value,
                              AIQuotaRejected if failure == "400" else AIOutcomeUnknown)
            assert len(calls) == count
            assert len(list(db.scalars(select(AIUsageReservation)))) == count
            assert [(r.status, r.accounted_cost) for r in rows] == charges


@pytest.mark.parametrize("failure", [
    "quota", "reserve_db", "scope_db", "400", "429", "unknown", "settle_db", "revoked",
])
def test_head_oracle_case_polish_http(persisted_draft, monkeypatch, failure):  # noqa: F811
    db, draft = persisted_draft
    client = FakePolishClient()
    original_call = client.complete_json
    attempts = []

    def call(**kw):
        attempts.append(time.monotonic())
        if failure in {"400", "429", "unknown"} and len(attempts) == 1:
            raise AIProviderError(
                "synthetic", code="HTTP_" + failure if failure != "unknown" else "OUTCOME_UNKNOWN",
                retryable=failure == "429", outcome_unknown=failure == "unknown",
                retry_after=.05 if failure == "429" else None,
            )
        if failure == "revoked":
            from app.models.classroom import AuthSession
            auth = db.get(AuthSession, db.info["case_actor"].session_id)
            auth.revoked_at = datetime.now(timezone.utc)
            db.commit()
        return original_call(**kw)

    client.complete_json = call
    armed = True

    def fail_commit(session):
        nonlocal armed
        reserve = any(isinstance(x, AIUsageReservation) for x in session.new)
        settle = any(isinstance(x, AIUsageReservation) for x in session.dirty)
        if armed and ((failure == "reserve_db" and reserve)
                      or (failure == "settle_db" and settle)):
            armed = False
            raise SQLAlchemyError("synthetic storage failure")

    event.listen(db, "before_commit", fail_commit)
    if failure == "scope_db":
        def fail_scope(*_, **__):
            raise SQLAlchemyError("synthetic scope storage failure")
        monkeypatch.setattr(db, "refresh", fail_scope)
    monkeypatch.setattr("app.knowledge.case_drafting.build_ai_client", lambda _: client)
    config = settings(**({"ai_daily_budget": 0} if failure == "quota" else {}))
    isolated = FastAPI()
    register_error_handlers(isolated)
    actor = db.get(User, db.info["case_actor"].user_id)
    actor._actor_context = db.info["case_actor"]
    draft_id = draft.id

    @isolated.post("/polish")
    def polish():
        return knowledge.polish_diagnosis_case_draft(draft_id, actor, db, config)

    try:
        with TestClient(isolated) as http:
            response = http.post("/polish")
        if failure == "429":
            assert response.status_code == 200
            assert len(attempts) == 2
            assert attempts[1] - attempts[0] >= .05
        elif failure == "revoked":
            assert response.status_code == 401
            assert response.json() == {"detail": {
                "code": "CURRENT_AUTHORIZATION_DENIED",
                "message": "current authorization is no longer valid",
            }}
        else:
            assert response.status_code == 409
            assert response.json() == {
                "detail": "AI case polish failed validation or quota check",
            }
        expected = 0 if failure in {"quota", "reserve_db", "scope_db"} else (
            2 if failure == "429" else 1
        )
        assert len(attempts) == expected
        db.rollback()
        rows = list(db.scalars(select(AIUsageReservation)))
        assert len(rows) == expected
        operation = db.scalar(select(AIOperation))
        assert (operation.status if operation else None) == {
            "quota": None, "reserve_db": None, "scope_db": None,
            "400": "failed_known", "429": "succeeded", "unknown": "outcome_unknown",
            "settle_db": "dispatching", "revoked": "succeeded",
        }[failure]
    finally:
        event.remove(db, "before_commit", fail_commit)


@pytest.mark.parametrize("error_type,category", [
    (AIQuotaRejected, ConflictError), (AIInputRejected, InvalidRequest),
    (AIScopeRejected, AccessDenied), (AIResultStale, StaleError),
    (AIStorageUnavailable, TemporarilyUnavailable), (AIOutcomeUnknown, ConflictError),
    (ProviderRequestRejected, InvalidRequest), (ProviderTemporaryFailure, TemporarilyUnavailable),
    (ProviderOutcomeUnknown, ConflictError),
])
def test_specific_errors_preserve_legacy_catches_and_certainty(error_type, category):
    error = error_type("SYNTHETIC")
    assert isinstance(error, AIProviderError)
    assert isinstance(error, category)
    if issubclass(error_type, AIQuotaDenied):
        assert isinstance(error, AIQuotaDenied)
    if error_type in {ProviderOutcomeUnknown, AIOutcomeUnknown}:
        assert error.outcome_unknown is True
        assert error.retryable is False
        assert not isinstance(error, TemporarilyUnavailable)
    else:
        assert error.outcome_unknown is False
        assert error.retryable is (error_type is ProviderTemporaryFailure)


@pytest.mark.parametrize("retryable,unknown,expected", [
    (False, False, ProviderRequestRejected), (True, False, ProviderTemporaryFailure),
    (False, True, ProviderOutcomeUnknown), (True, True, ProviderOutcomeUnknown),
])
def test_legacy_provider_adapter_never_grants_unknown_resend(retryable, unknown, expected):
    legacy = AIProviderError("safe", code="FIXED", status_code=429,
                             retryable=retryable, retry_after=3, outcome_unknown=unknown)
    classified = classified_provider_error(legacy)
    assert isinstance(classified, expected)
    assert (classified.code, classified.status_code, classified.retry_after) == ("FIXED", 429, 3)
    assert (classified.retryable and not classified.outcome_unknown) is (retryable and not unknown)


@pytest.mark.parametrize("values,expected", [
    ({"ai_enabled": False}, AIInputRejected),
    ({"ai_input_token_limit": 1}, AIInputRejected),
    ({"ai_daily_budget": 0}, AIQuotaRejected),
])
def test_preflight_refusals_are_classified_and_never_send(persisted_draft, values, expected):  # noqa: F811
    db, draft = persisted_draft
    provider = FakePolishClient()
    governor = GovernedAIInvocation(db, db.get(DiagnosisResult, draft.diagnosis_result_id),
                                    settings(**values), call_stage="preflight")
    with pytest.raises(expected):
        governor.complete_json(provider, system_prompt="long prompt", user_prompt="long prompt")
    assert not provider.prompts
    assert list(db.scalars(select(AIOperation))) == []
    assert list(db.scalars(select(AIUsageReservation))) == []


def test_scope_denial_and_storage_failure_do_not_claim_the_same_certainty(
    persisted_draft, monkeypatch,
):
    db, draft = persisted_draft
    diagnosis = db.get(DiagnosisResult, draft.diagnosis_result_id)
    monkeypatch.setattr("app.services.memory.diagnosis_sources_available", lambda *_: False)
    with pytest.raises(AIScopeRejected, match="AI_KNOWLEDGE_WITHDRAWN"):
        current_delivery_scope(db, diagnosis)
    failure = AuthorizationDenied(401)

    def revoke(*_, **__):
        raise failure

    monkeypatch.setattr(db, "refresh", revoke)
    with pytest.raises(AuthorizationDenied) as caught:
        current_delivery_scope(db, diagnosis)
    assert caught.value is failure


@pytest.mark.parametrize("operation", ["start", "review", "feedback"])
@pytest.mark.parametrize("wrapped", [False, True])
@pytest.mark.parametrize("error_type", [
    AIInputRejected, AIQuotaRejected, AIScopeRejected, AIResultStale, AIStorageUnavailable,
    AIOutcomeUnknown, ProviderRequestRejected, ProviderTemporaryFailure, ProviderOutcomeUnknown,
])
def test_classified_ai_errors_keep_workflow_legacy_503_and_rollback(
    boundary_context, monkeypatch, operation, wrapped, error_type,
):
    # XJ-013's pre-XJ-014 AIProviderError oracle: exact legacy 503 envelopes and
    # original request identity for all three real route adapters, even in nodes.
    assert_business_boundary(boundary_context, monkeypatch, operation, wrapped,
                             error_type("SYNTHETIC"), 503, None)
