"""Round 2 expectations come from XJ-004 rejection, not source implementation.

Transient failures must return 503 and leave all three business tables identical;
after recovery the same task/question/request can proceed. All fixtures use PG.
"""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from uuid import uuid4

import pytest
from psycopg import OperationalError as DriverOperationalError
from psycopg.errors import lookup
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError, OperationalError
from test_query_tasks import account_headers, answer_payload, begin, evidence
from test_query_tasks import api_context as postgres_api_context
from test_query_tasks import task as source_task_fixture

from app.core.errors import ConflictError, TemporarilyUnavailable
from app.models import (
    Device,
    Enrollment,
    ExperimentSession,
    QueryAnswerReceipt,
    QueryQuestion,
    QueryTask,
)
from app.services import query_sources, query_tasks

api_context = postgres_api_context
task = source_task_fixture


def saved_rows(task):
    # Independent connection observes committed state, including every timestamp,
    # manifest, count, status and receipt. No expectation is built by the service.
    with task["factory"]() as db:
        return {
            model.__tablename__: [
                dict(row) for row in db.execute(select(model.__table__)).mappings()
            ]
            for model in (QueryTask, QueryQuestion, QueryAnswerReceipt)
        }


def assert_retryable(response):
    assert response.status_code == 503, response.text
    assert response.json() == {"detail": "query_temporarily_unavailable"}


def break_loader(monkeypatch):
    def unavailable(*args, **kwargs):
        raise TemporarilyUnavailable("private-database-host and secret-source-payload")

    monkeypatch.setattr(query_sources, "load_experiment_package_runtime", unavailable)


@pytest.mark.parametrize("operation", ["start", "read", "answer"])
@pytest.mark.parametrize("entry", ["query", "delivery"])
@pytest.mark.parametrize("kind,status", [
    ("temporary", 503), ("database", 503), ("defect", 500), ("conflict", 409),
])
def test_xj013_source_fault_http_rolls_back_and_retains_request(
    api_context, task, monkeypatch, operation, entry, kind, status
):
    headers = {**account_headers(api_context, task), "X-Request-ID": "xj013-original"}
    client = api_context["client"]
    result = begin(task) if operation != "start" else None
    payload = answer_payload(result) if operation == "answer" else None
    before = saved_rows(task)
    failures = {
        "temporary": TemporarilyUnavailable("private source details"),
        "database": OperationalError("SQL", {}, DriverOperationalError("private DSN")),
        "defect": RuntimeError("private defect details"),
        "conflict": ConflictError("source conflict"),
    }
    with monkeypatch.context() as patch:
        def fail(*args):
            raise failures[kind]

        patch.setattr(query_sources, (
            "load_experiment_package_runtime" if entry == "query"
            else "diagnosis_sources_available"
        ), fail)
        if operation == "start":
            response = client.post(
                f"/api/v1/student/diagnoses/{task['diagnosis'].id}/queries", headers=headers
            )
        elif operation == "read":
            response = client.get(f"/api/v1/student/queries/{result['id']}", headers=headers)
        else:
            response = client.post(
                f"/api/v1/student/queries/{result['id']}/answers", headers=headers, json=payload
            )
        assert response.status_code == status, response.text
        assert response.headers["X-Request-ID"] == "xj013-original"
        assert "private" not in response.text
        if status == 503:
            assert response.json() == {"detail": "query_temporarily_unavailable"}
        elif status == 500:
            assert response.json() == {
                "detail": {"code": "INTERNAL_ERROR", "message": "Request failed"}
            }
        else:
            assert response.json() == {"detail": "source conflict"}
        assert saved_rows(task) == before
    if operation == "answer":
        recovered = client.post(
            f"/api/v1/student/queries/{result['id']}/answers", headers=headers, json=payload
        )
        assert recovered.status_code == 200, recovered.text
        assert recovered.json()["request_id"] == payload["request_id"]


def test_read_transient_failure_preserves_task_and_allows_answer(api_context, task, monkeypatch):
    result = begin(task)
    headers = account_headers(api_context, task)
    client = api_context["client"]
    path = f"/api/v1/student/queries/{result['id']}"
    before = saved_rows(task)
    with monkeypatch.context() as patch:
        break_loader(patch)
        assert_retryable(client.get(path, headers=headers))
        assert saved_rows(task) == before
    assert client.get(path, headers=headers).json() == result
    response = client.post(path + "/answers", headers=headers, json=answer_payload(result))
    assert response.status_code == 200, response.text


@pytest.mark.parametrize("late", [False, True], ids=["source-query", "after-task-flush"])
def test_start_transient_failure_creates_nothing_then_recovers(
    api_context, task, monkeypatch, late
):
    headers = account_headers(api_context, task)
    client = api_context["client"]
    path = f"/api/v1/student/diagnoses/{task['diagnosis'].id}/queries"
    before = saved_rows(task)
    assert all(rows == [] for rows in before.values())
    with monkeypatch.context() as patch:
        if late:
            original = query_tasks._deliver

            def fail_after_flush(db, *args):
                assert db.scalar(select(QueryTask)) is not None
                assert db.scalar(select(QueryQuestion)) is not None
                break_loader(patch)
                return original(db, *args)

            patch.setattr(query_tasks, "_deliver", fail_after_flush)
        else:
            break_loader(patch)
        assert_retryable(client.post(path, headers=headers))
        assert saved_rows(task) == before
    response = client.post(path, headers=headers)
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "waiting_answer"
    assert len(saved_rows(task)["query_tasks"]) == len(saved_rows(task)["query_questions"]) == 1


@pytest.mark.parametrize("late", [False, True], ids=["before-answer", "after-receipt-flush"])
def test_answer_transient_failure_rolls_back_and_same_request_recovers(
    api_context, task, monkeypatch, late
):
    result = begin(task)
    headers = account_headers(api_context, task)
    client = api_context["client"]
    path = f"/api/v1/student/queries/{result['id']}/answers"
    payload = answer_payload(result)
    before = saved_rows(task)
    with monkeypatch.context() as patch:
        if late:
            original = query_tasks._deliver

            def fail_after_flush(db, identity, session, record):
                if db.scalar(select(QueryAnswerReceipt)) is not None:
                    assert db.scalar(select(QueryQuestion.status)) == "closed"
                    break_loader(patch)
                return original(db, identity, session, record)

            patch.setattr(query_tasks, "_deliver", fail_after_flush)
        else:
            break_loader(patch)
        assert_retryable(client.post(path, headers=headers, json=payload))
        assert saved_rows(task) == before
    response = client.post(path, headers=headers, json=payload)
    assert response.status_code == 200, response.text
    assert client.post(path, headers=headers, json=payload).json() == response.json()
    assert len(saved_rows(task)["query_answer_receipts"]) == 1


def test_revocation_precedes_transient_failure_and_hides_existence(api_context, task, monkeypatch):
    result = begin(task)
    headers = account_headers(api_context, task)
    with task["factory"]() as db:
        db.query(Enrollment).update({"status": "withdrawn"})
        db.commit()
    before = saved_rows(task)
    break_loader(monkeypatch)
    responses = [
        api_context["client"].get(f"/api/v1/student/queries/{identifier}", headers=headers)
        for identifier in (result["id"], str(uuid4()))
    ]
    assert responses[0].status_code == responses[1].status_code == 403
    assert responses[0].json() == responses[1].json()
    assert saved_rows(task) == before


def test_ended_session_denial_precedes_exhausted_budget(api_context, task):
    result = begin(task)
    headers = account_headers(api_context, task)
    with task["factory"]() as db:
        record = db.get(QueryTask, result["id"])
        record.elapsed_ms = 120000
        session = db.get(ExperimentSession, task["identity"].session_id)
        session.status = "completed"
        session.ended_at = datetime.now(timezone.utc)
        db.commit()
    before = saved_rows(task)
    response = api_context["client"].post(
        f"/api/v1/student/queries/{result['id']}/answers",
        headers=headers,
        json=answer_payload(result),
    )
    assert response.status_code == 403, response.text
    assert saved_rows(task) == before


@pytest.mark.parametrize("kind", query_tasks.SOURCE_ORDER)
def test_single_query_error_cannot_be_adopted_even_if_revalidation_recovers(
    api_context, task, monkeypatch, kind
):
    headers = account_headers(api_context, task)
    path = f"/api/v1/student/diagnoses/{task['diagnosis'].id}/queries"
    before = saved_rows(task)
    source_type = type(query_sources.SOURCES[kind])
    original = source_type.query
    failed = []
    with monkeypatch.context() as patch:

        def fail_once(self, db, scope, requirement=None):
            if self.kind == kind and requirement is not None and not failed:
                failed.append(kind)
                return query_sources.SourceResult("error", reason_code="source_error")
            return original(self, db, scope, requirement)

        patch.setattr(source_type, "query", fail_once)
        assert_retryable(api_context["client"].post(path, headers=headers))
        assert saved_rows(task) == before
        assert failed == [kind]
    assert begin(task)["status"] == "waiting_answer"


def test_delivery_dependency_checker_fault_is_retryable(api_context, task, monkeypatch):
    result = begin(task)
    headers = account_headers(api_context, task)
    before = saved_rows(task)
    with monkeypatch.context() as patch:

        def fail_dependency(*args):
            raise TemporarilyUnavailable("private source details")

        patch.setattr(query_sources, "diagnosis_sources_available", fail_dependency)
        assert_retryable(
            api_context["client"].get(f"/api/v1/student/queries/{result['id']}", headers=headers)
        )
        assert saved_rows(task) == before
    assert query_tasks.read_query(task["db"], task["identity"], result["id"]) == result


@pytest.mark.parametrize("deleted", [False, True], ids=["evidence-modified", "evidence-deleted"])
def test_definite_evidence_change_is_stale_not_retryable(api_context, task, deleted):
    row = evidence(task)
    result = begin(task)
    assert result["requirements"]["firmware_gpio_vs_requirement"]["judgement"] == "match"
    headers = account_headers(api_context, task)
    if deleted:
        task["db"].delete(row)
    else:
        row.raw_payload = {"event_code": "DHT11_READ_FAILED", "sensor_snapshot": {"gpio": 5}}
    task["db"].commit()
    response = api_context["client"].get(f"/api/v1/student/queries/{result['id']}", headers=headers)
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "stale"
    assert response.json()["requirements"]["firmware_gpio_vs_requirement"]["judgement"] == "unknown"
    assert saved_rows(task)["query_tasks"][0]["status"] == "stale"


def test_real_lock_timeout_returns_http_503_without_task(api_context, task, monkeypatch):
    headers = account_headers(api_context, task)
    before = saved_rows(task)
    path = f"/api/v1/student/diagnoses/{task['diagnosis'].id}/queries"
    with monkeypatch.context() as patch:
        patch.setattr(query_tasks, "ACTIVE_SECONDS", 0.3)
        with task["factory"]() as blocker, ThreadPoolExecutor(max_workers=1) as pool:
            blocker.scalar(
                select(Device).where(Device.id == task["identity"].device_id).with_for_update()
            )
            future = pool.submit(api_context["client"].post, path, headers=headers)
            assert_retryable(future.result(timeout=5))
            blocker.rollback()
        assert saved_rows(task) == before
    assert begin(task)["status"] == "waiting_answer"


@pytest.mark.parametrize("state", [None, "08006", "40001", "40P01", "55P03", "57014"])
def test_database_transient_error_classification_rolls_back(api_context, task, monkeypatch, state):
    # Synthetic driver errors test the boundary mapping; statement and lock
    # timeout tests below/above separately exercise real PostgreSQL failures.
    result = begin(task)
    headers = account_headers(api_context, task)
    before = saved_rows(task)
    with monkeypatch.context() as patch:

        def failed_loader(*args):
            original = (
                lookup(state)("private connection details")
                if state
                else (DriverOperationalError("private connection details"))
            )
            raise OperationalError(None, None, original)

        patch.setattr(query_sources, "load_experiment_package_runtime", failed_loader)
        assert_retryable(
            api_context["client"].get(f"/api/v1/student/queries/{result['id']}", headers=headers)
        )
        assert saved_rows(task) == before
    assert query_tasks.read_query(task["db"], task["identity"], result["id"]) == result


@pytest.mark.parametrize("command", ["start", "read", "answer"])
def test_real_statement_timeout_is_retryable_and_rolls_back(
    api_context, task, monkeypatch, command
):
    result = begin(task) if command != "start" else None
    if result:
        record = task["db"].get(QueryTask, result["id"])
        record.elapsed_ms = 0
        task["db"].commit()
    headers = account_headers(api_context, task)
    client = api_context["client"]
    before = saved_rows(task)
    timed_out = []
    with monkeypatch.context() as patch:

        def slow_loader(db, *args):
            try:
                db.execute(text("SELECT pg_sleep(2)"))
            except DBAPIError as exc:
                timed_out.append(exc.orig.sqlstate)
                raise
            raise AssertionError("statement timeout did not occur")

        patch.setattr(query_tasks, "ACTIVE_SECONDS", 0.5)
        patch.setattr(query_sources, "load_experiment_package_runtime", slow_loader)
        if command == "start":
            response = client.post(
                f"/api/v1/student/diagnoses/{task['diagnosis'].id}/queries", headers=headers
            )
        elif command == "read":
            response = client.get(f"/api/v1/student/queries/{result['id']}", headers=headers)
        else:
            response = client.post(
                f"/api/v1/student/queries/{result['id']}/answers",
                headers=headers,
                json=answer_payload(result),
            )
        assert_retryable(response)
        assert timed_out == ["57014"]
        assert saved_rows(task) == before
    if command == "start":
        assert begin(task)["status"] == "waiting_answer"
    else:
        assert query_tasks.read_query(task["db"], task["identity"], result["id"]) == result
