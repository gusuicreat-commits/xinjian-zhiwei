"""XJ-013: independently injected failures, legacy bodies and transaction rollback."""

import ast
import logging
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from psycopg.errors import lookup
from sqlalchemy import select
from sqlalchemy.exc import DBAPIError, OperationalError, ProgrammingError
from test_query_tasks import api_context as postgres_api_context

from app.ai import diagnosis_graph
from app.ai.clients import AIProviderError
from app.ai.diagnosis_graph import DiagnosisNodeExecutionError, is_temporary_failure, observed_node
from app.api import dependencies
from app.api.errors import register_error_handlers
from app.api.http_boundary import ResponseBoundary
from app.api.v1.routes import diagnosis_workflows, health, student
from app.core.config import Settings
from app.core.errors import (
    AccessDenied,
    ConflictError,
    InvalidRequest,
    StaleError,
    TemporarilyUnavailable,
)
from app.diagnosis.workflow_schemas import (
    DiagnosisWorkflowReviewRequest,
    DiagnosisWorkflowStartRequest,
)
from app.main import unhandled_error
from app.models import Device, DiagnosisResult, DiagnosisWorkflowRun
from app.schemas.student import StudentFeedbackCreate
from app.services import device_ingest, query_sources
from app.services.auth import AuthorizationDenied

api_context = postgres_api_context
REQUEST_ID = "b0fab0f0-e59a-4cd8-9a88-457219114213"
INTERNAL = {"detail": {"code": "INTERNAL_ERROR", "message": "Request failed"}}
LEGACY = {
    "start": {"code": "DIAGNOSIS_WORKFLOW_FAILED", "message":
              "workflow failed; the legacy deterministic diagnosis remains available"},
    "review": {"code": "DIAGNOSIS_WORKFLOW_RESUME_FAILED", "message":
               "workflow resume failed; review can be retried after recovery"},
    "feedback": {"code": "DIAGNOSIS_FEEDBACK_RETRY_REQUIRED", "message":
                 "retry the same request_id and payload; do not create a new submission"},
}


def sql_failure(state, error_type=DBAPIError):
    return error_type("synthetic SQL", {}, lookup(state)("private database detail"))


FAILURES = [
    (AccessDenied("denied"), 403, {"detail": "denied"}),
    (ConflictError("conflict"), 409, {"detail": "conflict"}),
    (InvalidRequest("invalid"), 422, {"detail": "invalid"}),
    (StaleError("stale"), 409, {"detail": "stale"}),
    (AuthorizationDenied(401), 401, None),
    (TemporarilyUnavailable("private detail"), 503, None),
    (OperationalError("sql", {}, Exception("private DSN")), 503, None),
    *[(sql_failure(state), 503, None) for state in (
        "57014", "55P03", "40001", "40P01", "08006",
    )],
    (RuntimeError("private defect detail"), 500, INTERNAL),
    (sql_failure("42601", ProgrammingError), 500, INTERNAL),
    # XJ-013 explicitly excludes Provider classification/billing. Preserve its
    # legacy adapter, without granting permission to repeat an unknown send.
    (AIProviderError("private provider detail", code="OUTCOME_UNKNOWN"), 503, None),
]


class SessionProxy:
    """Only bypass row lookup of the two boundary inputs; use real SQL for writes."""

    def __init__(self, db, device):
        self.db, self.device = db, device

    def __getattr__(self, name):
        return getattr(self.db, name)

    def get(self, model, identifier, **kwargs):
        if model is DiagnosisWorkflowRun:
            return SimpleNamespace(id=identifier, device_id=self.device.id)
        return self.db.get(model, identifier, **kwargs)

    def scalar(self, statement, **kwargs):
        if statement.column_descriptions[0].get("entity") is DiagnosisResult:
            return SimpleNamespace(id="diagnosis", device_id=self.device.id)
        return self.db.scalar(statement, **kwargs)


@pytest.mark.parametrize("operation", ["start", "review", "feedback"])
@pytest.mark.parametrize("wrapped", [False, True], ids=["direct", "node-cause"])
@pytest.mark.parametrize("failure,status,body", FAILURES, ids=lambda x: type(x).__name__)
def test_business_boundary_classifies_and_rolls_back(
    api_context, monkeypatch, operation, wrapped, failure, status, body
):
    isolated = FastAPI()
    register_error_handlers(isolated)
    isolated.add_exception_handler(Exception, unhandled_error)
    isolated.state.diagnosis_graph = object()
    monkeypatch.setattr(dependencies, "student_actor_context", lambda *a: object())
    monkeypatch.setattr(diagnosis_workflows, "resolve_experiment_session", lambda *a: object())
    monkeypatch.setattr(diagnosis_workflows, "assert_workflow_ownership", lambda *a: None)
    monkeypatch.setattr(diagnosis_workflows, "user_access", lambda *a: (["admin"], []))
    captured = []
    with api_context["session_factory"]() as db:
        device = db.scalar(select(Device))
        before = device.display_name
        proxy = SessionProxy(db, device)

        def fail(*args, **kwargs):
            captured.extend(arg for arg in args if isinstance(arg, (
                DiagnosisWorkflowStartRequest, StudentFeedbackCreate,
                DiagnosisWorkflowReviewRequest,
            )))
            device.display_name = "uncommitted synthetic mutation"
            db.flush()
            if wrapped:
                raise DiagnosisNodeExecutionError("test_node", 1.25, type(failure).__name__) \
                    from failure
            raise failure

        monkeypatch.setattr(diagnosis_workflows, "run_check", fail)
        monkeypatch.setattr(diagnosis_workflows, "review_workflow", fail)
        monkeypatch.setattr(student, "submit_student_feedback", fail)

        @isolated.post("/failure")
        def invoke(request: Request):
            if operation == "start":
                return diagnosis_workflows.start_diagnosis_workflow(
                    device.device_key, DiagnosisWorkflowStartRequest(request_id=REQUEST_ID),
                    request, device, proxy, Settings(), api_context["experiment_session_id"],
                )
            if operation == "review":
                return diagnosis_workflows.review_diagnosis_workflow(
                    "original-workflow", DiagnosisWorkflowReviewRequest(action="approve"),
                    request, SimpleNamespace(id="reviewer"), proxy, Settings(),
                )
            return student.create_student_feedback(
                "diagnosis", StudentFeedbackCreate(request_id=REQUEST_ID, action="unresolved"),
                request, device, proxy, Settings(), api_context["experiment_session_id"],
            )

        boundary = ResponseBoundary(isolated, logging.getLogger("xj013-test"))
        with TestClient(boundary, raise_server_exceptions=False) as client:
            response = client.post("/failure", headers={"X-Request-ID": REQUEST_ID})
        assert response.status_code == status, response.text
        if status == 503:
            body = {"detail": LEGACY[operation]}
        elif isinstance(failure, AuthorizationDenied):
            body = {"detail": str(failure)} if operation != "feedback" else {
                "detail": {"code": "CURRENT_AUTHORIZATION_DENIED", "message": str(failure)}
            }
        assert response.json() == body
        assert response.headers["X-Request-ID"] == REQUEST_ID
        assert "private" not in response.text
        assert not db.in_transaction(), "the boundary must end the failed transaction"
        with api_context["session_factory"]() as check:
            assert check.get(Device, device.id).display_name == before
        assert len(captured) == 1
        if operation != "review":
            assert captured[0].request_id == UUID(REQUEST_ID)
        else:
            assert captured[0].action == "approve"


@pytest.mark.parametrize("failure,status,body", FAILURES[:4] + FAILURES[5:7] + FAILURES[12:13])
def test_observed_node_keeps_original_cause_and_bounded_metadata(
    monkeypatch, failure, status, body
):
    monkeypatch.setattr(diagnosis_graph, "_workflow", lambda *a: None)

    @observed_node("test_node")
    def fail(state, runtime):
        raise failure

    with pytest.raises(DiagnosisNodeExecutionError) as caught:
        fail({}, None)
    error = caught.value
    assert error.__cause__ is failure
    assert error.node == "test_node" and error.duration_ms >= 0
    assert error.error_type == type(failure).__name__
    assert error.original_error is failure
    assert "private" not in str(error)
    assert not isinstance(error, TemporarilyUnavailable)


@pytest.mark.parametrize("failure,status,body", [
    *FAILURES[:4],
    (ValueError("private invalid input"), 422, {"detail": "invalid_query_request"}),
])
def test_query_command_preserves_categories_and_legacy_value_error(
    api_context, failure, status, body
):
    isolated = FastAPI()
    register_error_handlers(isolated)
    with api_context["session_factory"]() as db:
        device = db.scalar(select(Device))
        device_id, before = device.id, device.display_name

        def fail(db):
            device.display_name = "uncommitted query mutation"
            db.flush()
            raise failure

        @isolated.post("/query")
        def invoke():
            return student._query_command(db, fail)

        boundary = ResponseBoundary(isolated, logging.getLogger("xj013-query-adapter"))
        with TestClient(boundary) as client:
            response = client.post("/query", headers={"X-Request-ID": REQUEST_ID})
        assert (response.status_code, response.json()) == (status, body)
        assert response.headers["X-Request-ID"] == REQUEST_ID
        assert not db.in_transaction()
        with api_context["session_factory"]() as check:
            assert check.get(Device, device_id).display_name == before


@pytest.mark.parametrize("state", ["42601", "23505", "22003"])
def test_nontransient_database_errors_are_not_retryable(state):
    assert not is_temporary_failure(sql_failure(state))


def test_nested_node_causes_and_unclassified_envelopes():
    original = ConflictError("conflict")
    inner = DiagnosisNodeExecutionError("inner", 1, "ConflictError")
    outer = DiagnosisNodeExecutionError("outer", 2, "DiagnosisNodeExecutionError")
    inner.__cause__ = original
    outer.__cause__ = inner
    assert outer.original_error is original
    assert not is_temporary_failure(outer)
    unknown = DiagnosisNodeExecutionError("unknown", 1, "Unknown")
    assert unknown.original_error is unknown and not is_temporary_failure(unknown)


@pytest.mark.parametrize("failure", [
    ConflictError("conflict"), OperationalError("sql", {}, Exception("private")),
    RuntimeError("private defect"),
])
def test_readiness_preserves_probe_contract_and_has_unavailable_semantics(failure):
    db = SimpleNamespace(execute=lambda *_: (_ for _ in ()).throw(failure))
    with pytest.raises(TemporarilyUnavailable) as caught:
        health.readiness(db)
    assert caught.value.status_code == 503
    assert caught.value.detail == {
        "code": "DATABASE_UNAVAILABLE", "message": type(failure).__name__,
    }
    assert caught.value.__cause__ is failure
    isolated = FastAPI()
    register_error_handlers(isolated)
    isolated.get("/ready")(lambda: health.readiness(db))
    boundary = ResponseBoundary(isolated, logging.getLogger("xj013-probe"))
    with TestClient(boundary) as client:
        response = client.get("/ready", headers={"X-Request-ID": REQUEST_ID})
    assert response.status_code == 503
    assert response.json() == {"detail": caught.value.detail}
    assert response.headers["X-Request-ID"] == REQUEST_ID


def test_protocol_envelope_producers_have_consistent_instance_retryability():
    tree = ast.parse(Path(device_ingest.__file__).read_text())
    statuses = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name):
            continue
        if node.func.id != "ProtocolIngestError":
            continue
        keywords = {kw.arg: kw.value for kw in node.keywords}
        expression = keywords["status_code"] if "status_code" in keywords else node.args[0]
        variants = [expression.body, expression.orelse] if isinstance(
            expression, ast.IfExp
        ) else [expression]
        retryable = ast.literal_eval(keywords["retryable"]) if "retryable" in keywords else False
        for variant in variants:
            status = ast.literal_eval(variant)
            assert status in {401, 403, 409, 413, 422, 429}
            assert retryable == (status == 429)
            statuses.append(status)
    assert set(statuses) == {401, 403, 409, 413, 422, 429}


@pytest.mark.parametrize("entry", ["query", "delivery"])
@pytest.mark.parametrize("failure", [
    AccessDenied("denied"), ConflictError("conflict"), InvalidRequest("invalid"),
    StaleError("stale"), RuntimeError("private defect"),
    OperationalError("sql", {}, Exception("private database")),
])
def test_source_classified_and_unexpected_failures_propagate(monkeypatch, entry, failure):
    def fail(*args):
        raise failure

    monkeypatch.setattr(query_sources, "_resolve", fail)
    with pytest.raises(type(failure)) as caught:
        if entry == "query":
            query_sources.SOURCES["package_requirement"].query(None, None)
        else:
            query_sources.revalidate_delivery(None, None, {})
    assert caught.value is failure


@pytest.mark.parametrize("entry", ["query", "delivery"])
@pytest.mark.parametrize("failure", [TemporarilyUnavailable("private"), OSError("private")])
def test_source_read_fault_stays_error_never_stale(monkeypatch, entry, failure):
    def fail(*args):
        raise failure

    monkeypatch.setattr(query_sources, "_resolve", fail)
    if entry == "query":
        result = query_sources.SOURCES["package_requirement"].query(None, None)
        assert result.status == "error" and result.reason_code == "source_error"
        assert result.units == result.manifest == ()
    else:
        assert query_sources.revalidate_delivery(None, None, {}) == "error"
