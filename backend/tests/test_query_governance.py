"""Independent task-wide attempt ceilings, at the shared actual dispatch gate."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from test_ai_quota_concurrency import CountingProvider, _diagnosis
from test_ai_quota_concurrency import quota_storage as quota_storage

from app.ai.governance import AIQuotaDenied, GovernedAIInvocation
from app.core.config import Settings
from app.models import DiagnosisResult
from app.models.ai_usage_reservation import AIUsageReservation


def test_actor_revoked_inside_provider_is_rechecked_before_return(quota_storage):  # noqa: F811
    _, _, engine = quota_storage
    access = [True]
    calls = []

    def recheck():
        if not access[0]:
            raise AIQuotaDenied("REVOKED")

    class Provider(CountingProvider):
        def complete_json(self, **kwargs):
            calls.append(1)
            access[0] = False
            return super().complete_json(**kwargs)

    with Session(engine) as db:
        diagnosis = _diagnosis(db)
        with pytest.raises(AIQuotaDenied, match="REVOKED"):
            GovernedAIInvocation(
                db,
                diagnosis,
                Settings(_env_file=None, ai_enabled=True),
                call_stage="post-access",
                recheck_access=recheck,
            ).complete_json(Provider(), system_prompt="s", user_prompt="u")
        assert len(calls) == 1
        assert db.scalar(select(func.count(AIUsageReservation.id))) == 1


def test_task_total_and_selection_attempts_include_all_stages_and_replay(quota_storage):  # noqa: F811
    from app.ai.governance import TaskAttemptLimits

    _, _, engine = quota_storage
    provider = CountingProvider()
    settings = Settings(
        _env_file=None, ai_enabled=True, ai_calls_per_device_hour=100, ai_calls_per_episode=100
    )
    with Session(engine, expire_on_commit=False) as db:
        diagnosis = _diagnosis(db)

        def call(stage, key):
            return GovernedAIInvocation(
                db,
                diagnosis,
                settings,
                call_stage=stage,
                operation_key=key,
                task_attempt_limits=TaskAttemptLimits(),
            ).complete_json(provider, system_prompt="s", user_prompt="u")

        for i in range(3):
            call("query_select", f"select-{i}")
        with pytest.raises(AIQuotaDenied, match="AI_SELECTION_ATTEMPTS_EXHAUSTED"):
            call("query_select", "select-4")
        call("reasoning", "reasoning")
        call("explanation", "explanation")
        call("query_select", "select-0")  # Success replay consumes zero new attempts.
        with pytest.raises(AIQuotaDenied, match="AI_TASK_ATTEMPTS_EXHAUSTED"):
            call("explanation", "sixth")
        assert provider.calls == 5
        assert db.scalar(select(func.count(AIUsageReservation.id))) == 5


def test_last_task_attempt_atomic_across_connections(quota_storage):  # noqa: F811
    from app.ai.governance import TaskAttemptLimits

    _, _, engine = quota_storage
    settings = Settings(_env_file=None, ai_enabled=True, ai_calls_per_device_hour=100)
    with Session(engine) as db:
        diagnosis_id = _diagnosis(db).id
    provider = CountingProvider()

    def worker(index):
        with Session(engine) as db:
            try:
                GovernedAIInvocation(
                    db,
                    db.get(DiagnosisResult, diagnosis_id),
                    settings,
                    call_stage="reasoning",
                    operation_key=f"parallel-{index}",
                    task_attempt_limits=TaskAttemptLimits(total=1),
                ).complete_json(provider, system_prompt="s", user_prompt="u")
                return "ok"
            except AIQuotaDenied as exc:
                return exc.code

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(worker, range(2)))
    assert sorted(results) == ["AI_TASK_ATTEMPTS_EXHAUSTED", "ok"]
    assert provider.calls == 1


def test_known_failure_retry_and_unknown_result_keep_cumulative_reservations(quota_storage):  # noqa: F811
    from app.ai.clients import AIProviderError
    from app.ai.governance import TaskAttemptLimits

    _, _, engine = quota_storage
    settings = Settings(
        _env_file=None, ai_enabled=True, ai_max_retries=1, ai_calls_per_device_hour=100
    )
    calls = []

    class FailThenSucceed(CountingProvider):
        def complete_json(self, **kwargs):
            calls.append(1)
            if len(calls) == 1:
                raise AIProviderError(
                    "retryable synthetic",
                    code="HTTP_429",
                    retryable=True,
                    retry_after=0,
                    outcome_unknown=False,
                )
            return super().complete_json(**kwargs)

    with Session(engine, expire_on_commit=False) as db:
        diagnosis = _diagnosis(db)
        governor = GovernedAIInvocation(
            db,
            diagnosis,
            settings,
            call_stage="query_select",
            task_attempt_limits=TaskAttemptLimits(total=2),
        )
        provider = FailThenSucceed()
        with pytest.raises(AIProviderError):
            governor.complete_json(provider, system_prompt="s", user_prompt="u")
        governor.complete_json(provider, system_prompt="s", user_prompt="u")
        # A new final stage omits limits; it still inherits the durable task ceiling.
        with pytest.raises(AIQuotaDenied, match="AI_TASK_ATTEMPTS_EXHAUSTED"):
            GovernedAIInvocation(db, diagnosis, settings, call_stage="explanation").complete_json(
                provider, system_prompt="s", user_prompt="u"
            )
        assert len(calls) == 2
        assert db.scalar(select(func.count(AIUsageReservation.id))) == 2


def test_governed_selection_success_before_checkpoint_replays_without_extra_attempt(tmp_path):
    import json

    from langgraph.checkpoint.memory import InMemorySaver
    from sqlalchemy import create_engine
    from test_query_contract import contract, evidence

    from app.ai.clients import AICompletion
    from app.ai.governance import TaskAttemptLimits
    from app.db.base import Base
    from app.evaluation.query_graph import (
        GovernedSelector,
        QueryRuntime,
        build_query_graph,
        run_query,
    )
    from app.evaluation.query_storage import QueryStore

    engine = create_engine(f"sqlite:///{tmp_path / 'joint.sqlite'}")
    Base.metadata.create_all(engine)
    store = QueryStore(engine)
    store.setup()
    c = contract(tools=["query_evidence", "query_approved_cases"])
    store.create(c)
    provider = CountingProvider()

    def completion(**kwargs):
        provider.calls += 1
        view = json.loads(kwargs["user_prompt"])
        return AICompletion(
            json.dumps(view["eligible_actions"][0]), input_tokens=20, output_tokens=10
        )

    provider.complete_json = completion
    with Session(engine, expire_on_commit=False) as db:
        diagnosis = _diagnosis(db)
        settings = Settings(_env_file=None, ai_enabled=True)
        selector = GovernedSelector(
            lambda key: GovernedAIInvocation(
                db,
                diagnosis,
                settings,
                call_stage="query_select",
                operation_key=key,
                task_attempt_limits=TaskAttemptLimits(),
            ),
            provider,
        )

        def die_after_completion(view, key):
            selector(view, key)
            raise KeyboardInterrupt("simulated process boundary after durable provider receipt")

        rt = QueryRuntime(
            store,
            "actor",
            {
                "query_evidence": lambda rid: [evidence(c)],
                "query_approved_cases": lambda rid: [evidence(c)],
            },
            selector=die_after_completion,
        )
        graph = build_query_graph(InMemorySaver())
        with pytest.raises(KeyboardInterrupt):
            run_query(graph, rt, "task")
        assert provider.calls == 1
        rt.selector = selector
        result = run_query(graph, rt, "task")
        assert result["status"] == "completed_satisfied"
        assert result["counts"]["selection_attempts"] == 1
        assert provider.calls == 1
        assert db.scalar(select(func.count(AIUsageReservation.id))) == 1


def _cumulative_worker(url, schema, diagnosis_id, start, release, messages):
    from test_ai_quota_concurrency import _engine

    from app.ai.clients import AICompletion

    engine = _engine(url, schema)

    class Provider:
        configured = True
        provider = "mock"
        model = "synthetic"

        def complete_json(self, **kwargs):
            messages.put("called")
            release.wait(15)
            return AICompletion("{}", input_tokens=1, output_tokens=1)

    try:
        with Session(engine) as db:
            settings = Settings(
                _env_file=None,
                ai_enabled=True,
                ai_output_token_limit=1000,
                ai_input_cost_per_1k_tokens=0,
                ai_output_cost_per_1k_tokens=0.01,
            )
            invocation = GovernedAIInvocation(
                db,
                db.get(DiagnosisResult, diagnosis_id),
                settings,
                call_stage="cumulative",
                cumulative_budget_limit=0.01,
            )
            messages.put("ready")
            start.wait(15)
            try:
                invocation.complete_json(Provider(), system_prompt="s", user_prompt="u")
                messages.put("succeeded")
            except AIQuotaDenied as exc:
                messages.put(exc.code)
    except Exception as exc:
        messages.put(type(exc).__name__)
    finally:
        engine.dispose()


def test_cumulative_money_one_remaining_reservation_across_processes(quota_storage):  # noqa: F811
    import multiprocessing

    url, schema, engine = quota_storage
    with Session(engine) as db:
        first = _diagnosis(db)
        second = DiagnosisResult(
            device_id=first.device_id,
            evaluated_at=first.evaluated_at,
            ruleset_version="test",
            ruleset_hash="test",
            input_fingerprint="other",
            context_snapshot={},
            is_test_data=True,
        )
        db.add(second)
        db.commit()
        ids = [first.id, second.id]
    ctx = multiprocessing.get_context("spawn")
    start, release, messages = ctx.Event(), ctx.Event(), ctx.Queue()
    workers = [
        ctx.Process(
            target=_cumulative_worker, args=(url, schema, identity, start, release, messages)
        )
        for identity in ids
    ]
    try:
        for worker in workers:
            worker.start()
        assert [messages.get(timeout=20) for _ in workers] == ["ready", "ready"]
        start.set()
        assert {messages.get(timeout=20) for _ in workers} == {
            "called",
            "AI_CUMULATIVE_BUDGET_LIMIT",
        }
        release.set()
        assert messages.get(timeout=20) == "succeeded"
        for worker in workers:
            worker.join(10)
            assert worker.exitcode == 0
        with Session(engine) as db:
            assert db.scalar(select(func.count(AIUsageReservation.id))) == 1
    finally:
        release.set()
        for worker in workers:
            if worker.is_alive():
                worker.terminate()
                worker.join(5)


@pytest.mark.parametrize("revocation", ["actor", "source"])
def test_reasoning_revocation_after_provider_keeps_usage_without_delivering(
    quota_storage, revocation,  # noqa: F811
):
    from uuid import uuid4

    from app.ai.reasoning import reason_about_causes
    from app.models import AICallRecord
    from app.services.auth import AuthorizationDenied

    _, _, engine = quota_storage
    access = [True]

    def recheck():
        if not access[0]:
            if revocation == "actor":
                raise AuthorizationDenied(403)
            raise AIQuotaDenied("AI_RESULT_STALE")

    class RevokingProvider(CountingProvider):
        def complete_json(self, **kwargs):
            completed = super().complete_json(**kwargs)
            access[0] = False
            return completed

    provider = RevokingProvider()
    evidence_id = str(uuid4())
    state = {
        "error_type": "TEST",
        "fault_tree_candidates": [{"cause_id": "cause", "name": "候选", "score": 0.5,
                                   "evidence_refs": [evidence_id]}],
        "evidence_registry": [{"id": evidence_id, "fact": "合成事实", "source": "rule",
                               "status": "observed"}],
    }
    with Session(engine, expire_on_commit=False) as db:
        diagnosis = _diagnosis(db)
        with pytest.raises(
            AuthorizationDenied if revocation == "actor" else AIQuotaDenied
        ):
            reason_about_causes(
                db, diagnosis, state,
                Settings(_env_file=None, ai_enabled=True, ai_max_retries=0,
                         ai_input_cost_per_1k_tokens=0.01,
                         ai_output_cost_per_1k_tokens=0.02),
                workflow_run_id=None, ai_client=provider,
                recheck_access=recheck,
            )
        db.rollback()
        assert provider.calls == 1
        usage = db.scalar(select(AIUsageReservation).where(
            AIUsageReservation.diagnosis_result_id == diagnosis.id,
        ))
        assert usage.status == "succeeded" and usage.accounted_cost > 0
        audit = db.scalar(select(AICallRecord).where(
            AICallRecord.diagnosis_result_id == diagnosis.id,
        ))
        assert audit is not None and audit.status == "succeeded"
        assert audit.output_json is None and audit.validation_status == "not_run"
        assert audit.error_code == (
            "AI_DELIVERY_ACCESS_REVOKED" if revocation == "actor" else "AI_RESULT_STALE"
        )
