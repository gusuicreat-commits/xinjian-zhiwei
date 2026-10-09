"""Opt affected recovery tests into the production error/response boundary.

The general evaluation environment deliberately only registers authorization.
These tests now exercise propagated 500s, so they need the real sanitized JSON
handler and response middleware instead of TestClient's raw exception rethrow.
Provider mocking, schemas, graph and session fixtures remain owned by the factory.
"""

import logging
from contextlib import contextmanager

from fastapi.testclient import TestClient

from app.api.errors import register_error_handlers
from app.api.http_boundary import ResponseBoundary
from app.evaluation.workflow_environment import workflow_environment as evaluation_environment
from app.main import unhandled_error


@contextmanager
def workflow_environment(*args, **kwargs):
    with evaluation_environment(*args, **kwargs) as env:
        register_error_handlers(env.app)
        env.app.add_exception_handler(Exception, unhandled_error)
        env.app.middleware_stack = env.app.build_middleware_stack()
        boundary = ResponseBoundary(env.app, logging.getLogger("xj013-recovery"))
        original_client = env.client
        with TestClient(boundary, raise_server_exceptions=False) as client:
            env.client = client
            try:
                yield env
            finally:
                env.client = original_client
