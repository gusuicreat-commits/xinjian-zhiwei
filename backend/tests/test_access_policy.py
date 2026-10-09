"""XJ-008: every effective HTTP operation has a reviewed access declaration."""

import importlib
import inspect
import re
from dataclasses import replace
from uuid import uuid4

import pytest
from fastapi import APIRouter, Depends, FastAPI
from fastapi.testclient import TestClient
from httpx import Response
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from starlette.routing import Route, WebSocketRoute

from app.api import dependencies
from app.api.access_policy import ACCESS_POLICIES, AccessPolicy, Auth
from app.api.v1.routes.student import _query_actor
from app.core.config import get_settings
from app.db.base import Base
from app.db.session import get_db
from app.main import app

HTTP_METHODS = {"get", "put", "post", "delete", "options", "head", "patch", "trace"}
AUTH_DEPENDENCIES = {
    dependencies.get_current_user: Auth.USER_TOKEN,
    dependencies.get_authenticated_device: Auth.DEVICE_TOKEN,
    dependencies.get_student_device: Auth.STUDENT_ACTOR,
    _query_actor: Auth.STUDENT_ACTOR,
    dependencies.require_review_access: Auth.REVIEW_TOKEN,
}
PERMISSION_CODE = dependencies.require_permission("inventory-probe").__code__
ROLE_CODE = dependencies.require_any_role("inventory-probe").__code__
HANDLER_AUTH = {"app.api.v1.routes.auth.logout": Auth.USER_TOKEN}
# Source-reviewed call edge: get_student_device's anonymous/demo branch calls
# get_authenticated_device directly. _query_actor rejects absent identity with
# 401 before that call, so it deliberately cannot use this 422 exception.
DEVICE_MISSING_CREDENTIALS_DEPENDENCIES = {
    dependencies.get_authenticated_device,
    dependencies.get_student_device,
}


def http_operations(application):
    """Use effective dependency trees, including inherited router dependencies.

    FastAPI's lazy included routers supply recursively expanded effective contexts.
    Plain APIRoute/Starlette Route remain supported. Unknown route containers fail
    loudly rather than silently omitting an HTTP surface (e.g. a future Mount).
    """
    operations = {}
    for branch in application.router.routes:
        contexts = (
            branch.effective_route_contexts()
            if hasattr(branch, "effective_route_contexts")
            else [branch]
        )
        for context in contexts:
            route = getattr(context, "starlette_route", None) or context
            if isinstance(route, WebSocketRoute):
                continue
            assert getattr(route, "methods", None), f"Unexpanded route container: {route!r}"
            assert isinstance(getattr(context, "original_route", route), Route)
            for method in route.methods:
                key = (method.upper(), route.path_format)
                assert key not in operations, f"Duplicate HTTP operation: {key}"
                operations[key] = route
    return operations


def dependency_calls(dependant):
    if dependant is None:
        return
    # Do not count the endpoint as its own authentication dependency.
    for child in dependant.dependencies:
        yield child.call
        yield from dependency_calls(child)


def assert_inventory_matches(operations, policies):
    missing = sorted(operations.keys() - policies.keys())
    stale = sorted(policies.keys() - operations.keys())
    assert not missing and not stale, f"Unregistered operations: {missing}; stale entries: {stale}"


def resolve_callable(qualified_name):
    module, name = qualified_name.rsplit(".", 1)
    result = getattr(importlib.import_module(module), name)
    assert callable(result), qualified_name
    return result


def assert_policy_matches(route, policy):
    calls = set(dependency_calls(getattr(route, "dependant", None)))
    actual_auth = {AUTH_DEPENDENCIES[call] for call in calls if call in AUTH_DEPENDENCIES}
    assert isinstance(policy.auth, Auth)
    assert isinstance(policy.writes, bool)
    if policy.auth_resolved_in_handler:
        assert policy.auth is not Auth.PUBLIC
        assert policy.auth_handler
        assert resolve_callable(policy.auth_handler) is route.endpoint
        assert HANDLER_AUTH[policy.auth_handler] is policy.auth
        assert not actual_auth, "Handler exception must not hide dependency authentication"
    else:
        assert policy.auth_handler is None
        expected = set() if policy.auth is Auth.PUBLIC else {policy.auth}
        assert actual_auth == expected, (
            f"auth mismatch: registered={expected}, actual={actual_auth}"
        )
    permission_codes, role_codes = set(), set()
    for call in calls:
        if not inspect.isfunction(call):
            continue
        values = inspect.getclosurevars(call).nonlocals
        if call.__code__ is PERMISSION_CODE:
            permission_codes.add(values["permission_code"])
        if call.__code__ is ROLE_CODE:
            role_codes.update(values["allowed_roles"])
    if policy.permission_checked_in_service:
        assert policy.permission and policy.access_notes
        # Dependency capabilities, when present, must agree with the service declaration.
        assert permission_codes <= set(re.split(r" \| | & ", policy.permission))
    else:
        assert permission_codes == ({policy.permission} if policy.permission else set())
    if role_codes:
        assert role_codes == set(policy.roles)
    elif policy.roles:
        assert policy.access_notes, "Handler/service roles require an explanation"
    if policy.auth is Auth.PUBLIC:
        assert policy.public_reason and policy.public_reason.strip()
        assert policy.permission is None and not policy.roles
        # In particular, public writes (login) need an explicit reviewed reason.
    else:
        assert policy.public_reason is None
    if policy.writes:
        assert type(policy.revalidates_in_transaction) is bool
        assert policy.transaction_evidence and policy.transaction_evidence.strip()
    else:
        assert policy.revalidates_in_transaction is None
        assert policy.transaction_evidence is None
    if policy.missing_credentials_status is None:
        assert policy.missing_credentials_code is None
        assert policy.missing_credentials_source is None
    else:
        assert policy.missing_credentials_status == 422
        assert policy.auth in {Auth.DEVICE_TOKEN, Auth.STUDENT_ACTOR}
        assert calls & DEVICE_MISSING_CREDENTIALS_DEPENDENCIES, (
            "422 missing-credential exception requires a reviewed device dependency"
        )
        assert policy.missing_credentials_code == "DEVICE_CREDENTIALS_REQUIRED"
        assert policy.missing_credentials_source
        assert (
            resolve_callable(policy.missing_credentials_source)
            is dependencies.get_authenticated_device
        )


def test_route_inventory_and_openapi_agree():
    operations = http_operations(app)
    assert_inventory_matches(operations, ACCESS_POLICIES)
    # Rebuild the schema so a stale OpenAPI cache cannot conceal a new operation.
    cached = app.openapi_schema
    try:
        app.openapi_schema = None
        schema = app.openapi()
    finally:
        app.openapi_schema = cached
    documented = {
        (method.upper(), path)
        for path, item in schema["paths"].items()
        for method in item
        if method in HTTP_METHODS
    }
    visible = {key for key, route in operations.items() if route.include_in_schema}
    assert documented == visible
    assert {
        ("GET", "/openapi.json"),
        ("HEAD", "/openapi.json"),
        ("GET", "/docs"),
        ("GET", "/redoc"),
        ("GET", "/docs/oauth2-redirect"),
    } <= operations.keys() - documented, "Hidden HTTP routes must also be enumerated"


@pytest.fixture(scope="module")
def operations():
    return http_operations(app)


@pytest.mark.parametrize(
    "key,policy",
    [pytest.param(key, policy, id=f"{key[0]} {key[1]}") for key, policy in ACCESS_POLICIES.items()],
)
def test_registered_dependency_policy(key, policy, operations):
    assert_policy_matches(operations[key], policy)


@pytest.fixture(scope="module")
def anonymous_client():
    # No application startup/checkpointer and no business database or Provider.
    engine = create_engine(
        "sqlite+pysqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    Base.metadata.create_all(engine)

    def database():
        with factory() as session:
            yield session

    settings = get_settings().model_copy(
        update={
            "ai_enabled": False,
            "diagnosis_workflow_enabled": False,
            "review_access_token": "xj-008-synthetic-review-secret",
        }
    )
    saved = app.dependency_overrides.copy()
    app.dependency_overrides.clear()
    app.dependency_overrides[get_db] = database
    app.dependency_overrides[get_settings] = lambda: settings
    client = TestClient(app)  # Deliberately no lifespan context.
    try:
        yield client
    finally:
        client.close()
        app.dependency_overrides.clear()
        app.dependency_overrides.update(saved)
        Base.metadata.drop_all(engine)
        engine.dispose()


PROTECTED_OPERATIONS = [
    pytest.param(key, policy, id=f"{key[0]} {key[1]}")
    for key, policy in ACCESS_POLICIES.items()
    if policy.auth is not Auth.PUBLIC
]


@pytest.mark.parametrize("key,policy", PROTECTED_OPERATIONS)
def test_anonymous_request_is_denied(key, policy, anonymous_client):
    method, template = key
    path = re.sub(r"\{[^}]+\}", lambda _: str(uuid4()), template)
    # Empty JSON is intentional: authentication must not be bypassed by bad input.
    kwargs = {"json": {}} if method in {"POST", "PUT", "PATCH"} else {}
    response = anonymous_client.request(method, path, follow_redirects=False, **kwargs)
    assert_anonymous_denied(key, policy, response)


def assert_anonymous_denied(key, policy, response):
    assert not 200 <= response.status_code < 300, f"Anonymous access: {key}: {response.text}"
    if policy.missing_credentials_status is not None:
        assert response.status_code == policy.missing_credentials_status, (
            f"{key}: expected missing-credential status={policy.missing_credentials_status}, "
            f"actual={response.status_code} {response.text}"
        )
        detail = response.json().get("detail")
        assert isinstance(detail, dict), f"{key}: expected detail.code, got {response.text}"
        assert detail.get("code") == policy.missing_credentials_code, (
            f"{key}: expected detail.code={policy.missing_credentials_code}, got {response.text}"
        )
    else:
        assert response.status_code in {401, 403}, f"{key}: {response.status_code} {response.text}"


def test_enumeration_includes_nested_hidden_routes_and_inherited_auth():
    isolated = FastAPI(openapi_url=None, docs_url=None, redoc_url=None)
    inner = APIRouter()

    @inner.get("/hidden", include_in_schema=False)
    def hidden():
        return {}

    outer = APIRouter(dependencies=[Depends(dependencies.get_current_user)])
    outer.include_router(inner, prefix="/inner")
    isolated.include_router(outer, prefix="/outer")
    found = http_operations(isolated)
    assert set(found) == {("GET", "/outer/inner/hidden")}
    assert_policy_matches(next(iter(found.values())), AccessPolicy(Auth.USER_TOKEN, None, False))


def test_gate_rejects_unregistered_and_stale_operations():
    with pytest.raises(AssertionError, match="Unregistered operations"):
        assert_inventory_matches({("GET", "/new"): object()}, {})
    with pytest.raises(AssertionError, match="stale entries"):
        assert_inventory_matches({}, {("GET", "/old"): AccessPolicy(Auth.PUBLIC, None, False)})


def test_gate_rejects_incorrect_auth_and_permission(operations):
    key = ("GET", "/api/v1/diagnosis-workflows/review-queue/pending")
    policy = ACCESS_POLICIES[key]
    with pytest.raises(AssertionError, match="auth mismatch"):
        assert_policy_matches(operations[key], replace(policy, auth=Auth.DEVICE_TOKEN))
    with pytest.raises(AssertionError):
        assert_policy_matches(operations[key], replace(policy, permission=None))


def test_gate_rejects_device_422_exception_on_user_or_query_actor(operations):
    for key in (
        ("GET", "/api/v1/auth/me"),
        ("GET", "/api/v1/student/queries/{task_id}"),
    ):
        policy = replace(
            ACCESS_POLICIES[key],
            missing_credentials_status=422,
            missing_credentials_code="DEVICE_CREDENTIALS_REQUIRED",
            missing_credentials_source="app.api.dependencies.get_authenticated_device",
        )
        with pytest.raises(AssertionError):
            assert_policy_matches(operations[key], policy)


@pytest.mark.parametrize(
    "status,detail",
    [
        (200, {"code": "DEVICE_CREDENTIALS_REQUIRED"}),
        (401, {"code": "DEVICE_CREDENTIALS_REQUIRED"}),
        (422, [{"loc": ["body", "field"], "type": "missing"}]),
        (422, {"code": "OTHER_ERROR"}),
        (422, {"message": "no code"}),
    ],
)
def test_gate_rejects_wrong_device_missing_credential_response(status, detail):
    key = ("POST", "/api/v1/device/ingest")
    with pytest.raises(AssertionError):
        assert_anonymous_denied(
            key, ACCESS_POLICIES[key], Response(status, json={"detail": detail})
        )


def test_gate_rejects_unregistered_422_response():
    key = ("GET", "/api/v1/auth/me")
    with pytest.raises(AssertionError):
        assert_anonymous_denied(
            key,
            ACCESS_POLICIES[key],
            Response(422, json={"detail": {"code": "DEVICE_CREDENTIALS_REQUIRED"}}),
        )
