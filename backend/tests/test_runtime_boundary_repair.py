"""Fail closed on unknown deployment names and preserve error envelopes."""

import pytest
from fastapi import APIRouter
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.core.config import Settings
from app.main import app


@pytest.mark.parametrize("environment", ["prd", "", "other"])
def test_unknown_environment_is_rejected(environment):
    with pytest.raises(ValidationError):
        Settings(app_env=environment, diagnosis_workflow_enabled=True)


def test_staging_cannot_use_memory_checkpoint():
    with pytest.raises(ValidationError):
        Settings(
            app_env="staging",
            diagnosis_workflow_enabled=True,
            diagnosis_checkpoint_backend="memory",
        )


def test_unhandled_error_has_safe_body_headers_and_request_id():
    router = APIRouter()

    @router.get("/_synthetic_unhandled")
    def fail():
        raise RuntimeError("synthetic-secret-do-not-emit")

    original_routes = list(app.router.routes)
    app.include_router(router)
    try:
        with TestClient(app, raise_server_exceptions=False) as client:
            response = client.get(
                "/_synthetic_unhandled", headers={"X-Request-ID": "synthetic-error-id"}
            )
        assert response.status_code == 500
        assert response.headers.get("X-Request-ID") == "synthetic-error-id"
        assert response.headers.get("X-Content-Type-Options") == "nosniff"
        assert response.json()["detail"]["code"] == "INTERNAL_ERROR"
        assert "synthetic-secret" not in response.text
    finally:
        app.router.routes[:] = original_routes
