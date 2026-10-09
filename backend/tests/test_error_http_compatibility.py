"""XJ-010: fixed HTTP expectations verified against unmodified HEAD 7d3bcc8.

Exercise production routes with isolated PG and real ingestion/diagnosis fixtures.
No real Provider calls; failure injection is limited to the package source loader.
"""

import pytest
from test_experiment_packages import PACKAGE_ROOT, _admin_headers
from test_query_tasks import account_headers, answer_payload, begin
from test_query_tasks import api_context as postgres_api_context
from test_query_tasks import real_task as pipeline_task_fixture

from app.experiment_packages.loader import load_experiment_package, package_documents
from app.models import Enrollment
from app.services import query_sources
from app.services.memory import package_source, register_stop

api_context = postgres_api_context
real_task = pipeline_task_fixture


@pytest.fixture
def http_task(real_task):
    return real_task([({"gpio": 4}, "0.2.5", "xj010-synthetic-boot")])


@pytest.mark.parametrize("revoked", [False, True], ids=["401", "403"])
def test_access_denied_keeps_current_authorization_envelope(api_context, http_task, revoked):
    headers = account_headers(api_context, http_task) if revoked else {}
    if revoked:
        with http_task["factory"]() as db:
            db.query(Enrollment).update({"status": "withdrawn"})
            db.commit()
    response = api_context["client"].post(
        f"/api/v1/student/diagnoses/{http_task['diagnosis'].id}/queries", headers=headers
    )
    assert response.status_code == (403 if revoked else 401)
    assert response.json() == {
        "detail": {
            "code": "CURRENT_AUTHORIZATION_DENIED",
            "message": "current authorization is no longer valid",
        }
    }


def test_conflict_keeps_string_detail(api_context, http_task):
    result = begin(http_task)
    payload = answer_payload(result)
    payload["question_version"] = "obsolete-version"
    response = api_context["client"].post(
        f"/api/v1/student/queries/{result['id']}/answers",
        headers=account_headers(api_context, http_task),
        json=payload,
    )
    assert response.status_code == 409
    assert response.json() == {"detail": "question_version_conflict"}


def test_invalid_package_keeps_422_string_detail(api_context):
    bundle, _ = load_experiment_package(PACKAGE_ROOT / "dht11_temperature_humidity")
    documents = package_documents(bundle)
    documents.pop("metadata.yaml")
    response = api_context["client"].post(
        "/api/v1/experiments/packages/validate",
        headers=_admin_headers(api_context),
        json={"documents": documents, "is_test_data": True},
    )
    assert response.status_code == 422
    assert response.json() == {
        "detail": "package file set mismatch: missing=['metadata.yaml'], extra=[]"
    }


def test_definitely_stale_source_keeps_200_projection(api_context, http_task):
    result = begin(http_task)
    register_stop(
        http_task["db"], package_source(http_task["version"]), http_task["student"],
        "xj010 synthetic source withdrawal",
    )
    http_task["db"].commit()
    response = api_context["client"].get(
        f"/api/v1/student/queries/{result['id']}",
        headers=account_headers(api_context, http_task),
    )
    assert response.status_code == 200
    assert response.json() == {
        "id": result["id"],
        "contract_version": "dht11-query-v1",
        "status": "stale",
        "terminal_reason": "source_stale",
        "requirements": {
            "firmware_gpio_vs_requirement": {
                "status": "stale", "judgement": "unknown", "gap": "source_stale",
            },
            "wiring_observation": {
                "status": "unknown", "judgement": "unknown", "gap": "observation_unknown",
            },
            "approved_reference": {
                "status": "stale", "judgement": "unknown", "gap": "source_stale",
            },
        },
        "question": None,
        "query_count": 4,
        "question_count": 1,
        "is_test_data": True,
        "root_cause_status": "unconfirmed",
        "physical_verification": "not_asserted",
    }


def test_source_failure_keeps_503_and_allows_recovery(api_context, http_task, monkeypatch):
    headers = account_headers(api_context, http_task)
    path = f"/api/v1/student/diagnoses/{http_task['diagnosis'].id}/queries"

    def fail_source(*args, **kwargs):
        raise RuntimeError("synthetic secret source payload")

    with monkeypatch.context() as patch:
        patch.setattr(query_sources, "load_experiment_package_runtime", fail_source)
        response = api_context["client"].post(path, headers=headers)
        assert response.status_code == 503
        assert response.json() == {"detail": "query_temporarily_unavailable"}
    response = api_context["client"].post(path, headers=headers)
    assert response.status_code == 200
    assert response.json()["status"] == "waiting_answer"
