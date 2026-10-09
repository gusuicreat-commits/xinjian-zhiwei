"""Real PostgreSQL, official saver, separate processes, explicit hard termination."""

from __future__ import annotations

import multiprocessing
import os
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from uuid import uuid4

import pytest
from langgraph.checkpoint.postgres import PostgresSaver
from psycopg.conninfo import make_conninfo
from sqlalchemy import create_engine, text
from test_query_contract import contract, evidence

from app.evaluation.query_graph import QueryRuntime, build_query_graph, run_query
from app.evaluation.query_storage import QueryRejected, QueryStore


def engine_for(dsn, schema):
    return create_engine(
        dsn.replace("postgresql://", "postgresql+psycopg://", 1),
        connect_args={"options": f"-csearch_path={schema}"},
    )


@contextmanager
def graph_for(dsn, schema):
    with PostgresSaver.from_conn_string(
        make_conninfo(dsn, options=f"-csearch_path={schema}")
    ) as saver:
        saver.setup()
        yield build_query_graph(saver)


@pytest.fixture
def pg():
    dsn = os.environ.get("XINJIAN_EVAL_POSTGRES_DSN")
    if not dsn:
        pytest.skip("explicit isolated PostgreSQL DSN required")
    schema = "query_eval_" + uuid4().hex
    admin = create_engine(dsn.replace("postgresql://", "postgresql+psycopg://", 1))
    with admin.begin() as conn:
        conn.execute(text(f"CREATE SCHEMA {schema}"))
    engine = engine_for(dsn, schema)
    store = QueryStore(engine)
    store.setup()
    try:
        yield dsn, schema, store
    finally:
        engine.dispose()
        with admin.begin() as conn:
            conn.execute(text(f"DROP SCHEMA {schema} CASCADE"))
        admin.dispose()


def submit(store, value="off", request="reply"):
    q = store.read("task")["question"]
    return store.submit_answer(
        "task",
        "actor",
        request_id=request,
        question_id=q["id"],
        question_version=q["version"],
        revision=q["revision"],
        value=value,
    )


def _child(dsn, schema, mode, ready, release, output):
    engine = engine_for(dsn, schema)
    store = QueryStore(engine)
    try:
        if mode in {"answer", "answer_then_die"}:
            result = submit(store)
            output.put(("receipt", result))
            if mode == "answer_then_die":
                ready.set()
                time.sleep(60)
            return
        with PostgresSaver.from_conn_string(
            make_conninfo(dsn, options=f"-csearch_path={schema}")
        ) as saver:
            saver.setup()
            original = saver.put

            def fault_put(*args, **kwargs):
                d = store.read("task")
                hit = (
                    (mode == "question_before_checkpoint" and d["question"])
                    or (
                        mode in {"answer_before_checkpoint", "answer_after_checkpoint"}
                        and d["question"]
                        and d["question"]["status"] == "consumed"
                    )
                    or (mode == "final_before_checkpoint" and d["status"] == "completed_satisfied")
                )
                if hit:
                    if mode == "answer_after_checkpoint":
                        result = original(*args, **kwargs)
                    ready.set()
                    time.sleep(60)
                    if mode == "answer_after_checkpoint":
                        return result
                return original(*args, **kwargs)

            saver.put = fault_put
            graph = build_query_graph(saver)

            def tool(rid):
                if mode == "tool_inflight":
                    ready.set()
                    time.sleep(60)
                return []

            rt = QueryRuntime(store, "actor", {"query_evidence": tool})
            result = run_query(graph, rt, "task")
            output.put(("result", result["status"]))
    except QueryRejected as exc:
        output.put(("rejected", str(exc)))
    finally:
        engine.dispose()


def launch(pg, mode):
    dsn, schema, _ = pg
    ctx = multiprocessing.get_context("spawn")
    ready, release, output = ctx.Event(), ctx.Event(), ctx.Queue()
    child = ctx.Process(target=_child, args=(dsn, schema, mode, ready, release, output))
    child.start()
    return child, ready, release, output


def kill_at_fault(pg, mode):
    child, ready, release, output = launch(pg, mode)
    try:
        assert ready.wait(15), f"child must reach {mode}"
        child.terminate()
        child.join(5)
        assert child.exitcode is not None and child.exitcode != 0
    finally:
        release.set()
        if child.is_alive():
            child.terminate()
            child.join(5)
        output.close()
        output.join_thread()


def wait_task(pg):
    dsn, schema, store = pg
    store.create(contract())
    with graph_for(dsn, schema) as graph:
        assert (
            run_query(
                graph, QueryRuntime(store, "actor", {"query_evidence": lambda r: []}), "task"
            )["status"]
            == "awaiting_answer"
        )


def test_connection_rebuild_then_answer_and_completed_replay(pg):
    dsn, schema, store = pg
    wait_task(pg)
    before = store.read("task")["active_seconds"]
    submit(store)
    store.engine.dispose()
    with graph_for(dsn, schema) as graph:
        result = run_query(graph, QueryRuntime(store, "actor", {}), "task")
        assert result["status"] == "completed_satisfied"
        assert result["counts"] == {"queries": 1, "questions": 1, "selection_attempts": 0}
        assert (
            run_query(graph, QueryRuntime(store, "actor", {}), "task")["counts"] == result["counts"]
        )
    assert store.read("task")["active_seconds"] >= before


def test_two_processes_same_answer_one_receipt_and_one_successor(pg):
    wait_task(pg)
    children = [launch(pg, "answer") for _ in range(2)]
    results = []
    try:
        for child, _, _, output in children:
            child.join(15)
            assert child.exitcode == 0
            results.append(output.get(timeout=3))
        assert results[0] == results[1]
        doc = pg[2].read("task")
        assert doc["revision"] == 2
        assert len(doc["receipts"]) == 1
        with pytest.raises(QueryRejected, match="answer_conflict"):
            submit(pg[2], "on")
    finally:
        for child, _, release, output in children:
            release.set()
            if child.is_alive():
                child.terminate()
                child.join(5)
            output.close()
            output.join_thread()


@pytest.mark.parametrize(
    "mode",
    [
        "answer_then_die",
        "answer_before_checkpoint",
        "answer_after_checkpoint",
        "final_before_checkpoint",
    ],
)
def test_process_death_after_business_receipt_never_consumes_twice(pg, mode):
    dsn, schema, store = pg
    wait_task(pg)
    if mode != "answer_then_die":
        submit(store)
    kill_at_fault(pg, mode)
    with graph_for(dsn, schema) as graph:
        result = run_query(graph, QueryRuntime(store, "actor", {}), "task")
    assert result["status"] == "completed_satisfied"
    doc = store.read("task")
    assert doc["revision"] == 2
    assert len(doc["receipts"]) == 1
    assert doc["counts"]["questions"] == 1
    assert doc["counts"]["queries"] == 1
    assert sum(s["kind"] == "answer_consumed" for s in doc["steps"]) == 1
    assert doc["owner"] is None


def test_process_death_after_registration_does_not_ask_again(pg):
    dsn, schema, store = pg
    store.create(contract())
    kill_at_fault(pg, "question_before_checkpoint")
    with graph_for(dsn, schema) as graph:
        result = run_query(graph, QueryRuntime(store, "actor", {}), "task")
        assert result["status"] == "awaiting_answer"
        assert result["counts"]["questions"] == 1
        submit(store, "unclear")
        assert (
            run_query(graph, QueryRuntime(store, "actor", {}), "task")["status"]
            == "completed_unknown"
        )


def test_process_death_during_tool_is_not_repeated(pg):
    dsn, schema, store = pg
    store.create(contract())
    kill_at_fault(pg, "tool_inflight")
    calls = []
    with graph_for(dsn, schema) as graph:
        result = run_query(
            graph,
            QueryRuntime(store, "actor", {"query_evidence": lambda r: calls.append(r) or []}),
            "task",
        )
    assert result["status"] == "outcome_unknown"
    assert calls == []
    assert store.read("task")["counts"]["queries"] == 1
    assert store.read("task")["active_seconds"] > 0


def test_concurrent_process_resume_is_exclusive_and_consumes_once(pg):
    wait_task(pg)
    submit(pg[2])
    children = [launch(pg, "resume") for _ in range(2)]
    try:
        results = []
        for child, _, _, output in children:
            child.join(15)
            assert child.exitcode == 0
            results.append(output.get(timeout=3))
        assert ("result", "completed_satisfied") in results
        assert all(
            r in {("result", "completed_satisfied"), ("rejected", "already_running")}
            for r in results
        )
        doc = pg[2].read("task")
        assert len(doc["receipts"]) == 1
        assert sum(s["kind"] == "answer_consumed" for s in doc["steps"]) == 1
    finally:
        for child, _, release, output in children:
            release.set()
            if child.is_alive():
                child.terminate()
                child.join(5)
            output.close()
            output.join_thread()


def test_query_wait_holds_no_db_lock_revocation_wins(pg):
    dsn, schema, store = pg
    c = contract()
    store.create(c)

    def tool(rid):
        with store.edit("task") as doc:
            doc["sources_valid"] = False
        return [evidence(c)]

    with graph_for(dsn, schema) as graph:
        result = run_query(graph, QueryRuntime(store, "actor", {"query_evidence": tool}), "task")
    assert result["evidence"] == []
    assert store.read("task")["records"] == []


def test_external_authorization_rechecked_at_postgres_answer_commit(pg):
    dsn, schema, store = pg
    c = contract()
    store.create(c)
    with graph_for(dsn, schema) as graph:
        first = run_query(
            graph, QueryRuntime(store, "actor", {"query_evidence": lambda r: []}), "task"
        )
    q = first["question"]
    access = [False]

    def recheck(doc):
        if not access[0]:
            raise QueryRejected("revoked")

    with pytest.raises(QueryRejected, match="unavailable"):
        store.submit_answer(
            "task", "actor", request_id="same-request", question_id=q["id"],
            question_version=q["version"], revision=q["revision"], value="off",
            recheck=recheck,
        )
    assert store.read("task")["receipts"] == {}
    access[0] = True
    receipt = store.submit_answer(
        "task", "actor", request_id="same-request", question_id=q["id"],
        question_version=q["version"], revision=q["revision"], value="off",
        recheck=recheck,
    )
    assert receipt["request_id"] == "same-request"
    assert len(store.read("task")["receipts"]) == 1


def test_different_content_race_preserves_original_receipt(pg):
    wait_task(pg)

    def worker(value):
        try:
            return submit(pg[2], value)["hash"]
        except QueryRejected as exc:
            return str(exc)

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(worker, ["on", "off"]))
    assert results.count("answer_conflict") == 1
    assert len(pg[2].read("task")["receipts"]) == 1


def _model_child(dsn, schema, diagnosis_id, phase, ready):
    from sqlalchemy.orm import Session

    from app.ai.clients import AICompletion
    from app.ai.governance import GovernedAIInvocation, TaskAttemptLimits
    from app.core.config import Settings
    from app.models import DiagnosisResult

    class Provider:
        provider = "local-test"
        model = "synthetic"
        configured = True

        def complete_json(self, **kwargs):
            if phase == "after_dispatch":
                ready.set()
                time.sleep(60)
            return AICompletion("{}", input_tokens=1, output_tokens=1)

    engine = engine_for(dsn, schema)
    with Session(engine, expire_on_commit=False) as db:
        governor = GovernedAIInvocation(
            db,
            db.get(DiagnosisResult, diagnosis_id),
            Settings(_env_file=None, ai_enabled=True),
            call_stage="query_select",
            operation_key="stable-select",
            task_attempt_limits=TaskAttemptLimits(),
        )
        governor.complete_json(Provider(), system_prompt="s", user_prompt="u")
        ready.set()
        time.sleep(60)


@pytest.mark.parametrize("phase", ["after_dispatch", "after_settlement"])
def test_model_process_death_does_not_repeat_dispatch_or_reset_attempts(pg, phase):
    from sqlalchemy import func, select
    from sqlalchemy.orm import Session
    from test_ai_quota_concurrency import CountingProvider, _diagnosis

    from app.ai.governance import AIQuotaDenied, GovernedAIInvocation, TaskAttemptLimits
    from app.core.config import Settings
    from app.db.base import Base
    from app.models import DiagnosisResult
    from app.models.ai_usage_reservation import AIUsageReservation

    dsn, schema, store = pg
    Base.metadata.create_all(store.engine)
    with Session(store.engine) as db:
        diagnosis_id = _diagnosis(db).id
    ctx = multiprocessing.get_context("spawn")
    ready = ctx.Event()
    child = ctx.Process(target=_model_child, args=(dsn, schema, diagnosis_id, phase, ready))
    child.start()
    try:
        assert ready.wait(15)
        child.terminate()
        child.join(5)
        assert child.exitcode != 0
        provider = CountingProvider()
        provider.provider = "local-test"
        provider.model = "synthetic"
        with Session(store.engine) as db:
            governor = GovernedAIInvocation(
                db,
                db.get(DiagnosisResult, diagnosis_id),
                Settings(_env_file=None, ai_enabled=True),
                call_stage="query_select",
                operation_key="stable-select",
                task_attempt_limits=TaskAttemptLimits(),
            )
            if phase == "after_dispatch":
                with pytest.raises(AIQuotaDenied, match="AI_OUTCOME_UNKNOWN"):
                    governor.complete_json(provider, system_prompt="s", user_prompt="u")
            else:
                assert (
                    governor.complete_json(provider, system_prompt="s", user_prompt="u").content
                    == "{}"
                )
            assert provider.calls == 0
            assert db.scalar(select(func.count(AIUsageReservation.id))) == 1
    finally:
        if child.is_alive():
            child.terminate()
            child.join(5)
