"""Classification, legacy catch compatibility and the central HTTP boundary."""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.ai.clients import AIProviderError
from app.ai.context_sanitizer import ProviderInputError
from app.ai.diagnosis_graph import DiagnosisNodeExecutionError
from app.ai.governance import AIQuotaDenied
from app.api.errors import register_error_handlers
from app.core.errors import (
    AccessDenied,
    ConflictError,
    DomainError,
    InvalidRequest,
    StaleError,
    TemporarilyUnavailable,
)
from app.experiment_packages.loader import ExperimentPackageLoadError
from app.experiments.loader import ExperimentDefinitionLoadError
from app.knowledge.case_drafting import CaseDraftError
from app.main import app as production_app
from app.services.auth import AuthorizationDenied
from app.services.data_scope import ScopeConflict, ScopeViolation
from app.services.device_ingest import ProtocolIngestError
from app.services.diagnosis_episode import EpisodeFeedbackConflict
from app.services.internal_experiment_preparation import PreparationError
from app.services.interventions import InterventionConflict
from app.services.memory_governance import MemoryConflict
from app.services.query_sources import _Stale
from app.services.query_tasks import QueryConflict, QueryUnavailable


@pytest.mark.parametrize(
    "error_type, category, legacy_base",
    [
        (AuthorizationDenied, AccessDenied, PermissionError),
        (ScopeViolation, AccessDenied, PermissionError),
        (ScopeConflict, ConflictError, ValueError),
        (QueryConflict, ConflictError, ValueError),
        (InterventionConflict, ConflictError, ValueError),
        (MemoryConflict, ConflictError, ValueError),
        (EpisodeFeedbackConflict, ConflictError, ValueError),
        (CaseDraftError, ConflictError, ValueError),
        (PreparationError, InvalidRequest, ValueError),
        (ExperimentPackageLoadError, InvalidRequest, ValueError),
        (ExperimentDefinitionLoadError, InvalidRequest, ValueError),
        (ProviderInputError, InvalidRequest, ValueError),
        (_Stale, StaleError, ValueError),
        (QueryUnavailable, TemporarilyUnavailable, RuntimeError),
    ],
)
def test_existing_errors_preserve_catch_compatibility(error_type, category, legacy_base):
    assert issubclass(error_type, category)
    assert issubclass(error_type, legacy_base)
    assert isinstance(error_type.error_code, str) and error_type.error_code


@pytest.mark.parametrize(
    "exc, status, body",
    [
        (AccessDenied("scope denied"), 403, {"detail": "scope denied"}),
        (ScopeViolation("scope denied"), 403, {"detail": "scope denied"}),
        (
            AuthorizationDenied(401), 401,
            {"detail": {"code": "CURRENT_AUTHORIZATION_DENIED",
                        "message": "current authorization is no longer valid"}},
        ),
        (
            AuthorizationDenied(403), 403,
            {"detail": {"code": "CURRENT_AUTHORIZATION_DENIED",
                        "message": "current authorization is no longer valid"}},
        ),
        (ScopeConflict("version changed"), 409, {"detail": "version changed"}),
        (InvalidRequest("invalid request"), 422, {"detail": "invalid request"}),
        (_Stale(), 409, {"detail": "source_stale"}),
        (QueryUnavailable(), 503, {"detail": "query_temporarily_unavailable"}),
        (
            TemporarilyUnavailable("private-dsn-and-source-payload"), 503,
            {"detail": "TEMPORARILY_UNAVAILABLE"},
        ),
    ],
)
def test_registered_http_handlers_preserve_detail_contract_and_redact_transient_error(
    exc, status, body
):
    isolated = FastAPI()
    register_error_handlers(isolated)

    @isolated.get("/failure")
    def failure():
        raise exc

    with TestClient(isolated) as client:
        response = client.get("/failure")
    assert response.status_code == status
    assert response.json() == body
    for category in (
        AccessDenied, ConflictError, InvalidRequest, StaleError, TemporarilyUnavailable,
        AuthorizationDenied,
    ):
        assert production_app.exception_handlers[category] is isolated.exception_handlers[category]


def test_mixed_legacy_wrappers_do_not_invent_retryable_failures():
    # A known rejection / unknown send / arbitrary node error / multi-status
    # protocol envelope cannot truthfully acquire a single retryable category.
    for error_type in (
        AIProviderError, AIQuotaDenied, DiagnosisNodeExecutionError, ProtocolIngestError
    ):
        assert issubclass(error_type, DomainError)
        assert not issubclass(error_type, TemporarilyUnavailable)
    provider = AIProviderError("unknown send", code="OUTCOME_UNKNOWN")
    assert isinstance(provider, RuntimeError)
    assert provider.outcome_unknown is True and provider.retryable is False
    assert isinstance(DiagnosisNodeExecutionError("test", 1.0, "TypeError"), RuntimeError)
    protocol = ProtocolIngestError(413, "PAYLOAD_TOO_LARGE", "too large", "request", {})
    assert protocol.status_code == 413 and protocol.error_code == "PAYLOAD_TOO_LARGE"
