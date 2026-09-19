"""BR-SESSION: commands are scoped, atomic, retryable and preserve old ownership."""

from uuid import uuid4

from sqlalchemy import select
from test_business_identity import account_headers

from app.models import DeviceBinding, ExperimentAssignment, ExperimentSession
from app.models.base import utc_now


def prepare(api_context):
    headers = account_headers(api_context)
    with api_context["session_factory"]() as db:
        session = db.get(ExperimentSession, api_context["experiment_session_id"])
        assignment = db.get(ExperimentAssignment, session.experiment_assignment_id)
        db.add(
            DeviceBinding(
                device_id=session.device_id,
                class_id=assignment.class_id,
                student_user_id=session.student_user_id,
                experiment_assignment_id=assignment.id,
                is_active=True,
            )
        )
        payload = {
            "request_id": str(uuid4()),
            "device_id": "phase2-test-device",
            "experiment_assignment_id": assignment.id,
        }
        db.commit()
    return headers, payload


def test_busy_device_cannot_be_acquired(api_context):
    headers, payload = prepare(api_context)
    response = api_context["client"].post(
        "/api/v1/student/experiment-sessions", headers=headers, json=payload
    )
    assert response.status_code == 409
    with api_context["session_factory"]() as db:
        assert len(list(db.scalars(select(ExperimentSession)))) == 1


def test_start_retries_return_same_receipt_and_changed_request_conflicts(api_context):
    headers, payload = prepare(api_context)
    with api_context["session_factory"]() as db:
        session = db.get(ExperimentSession, api_context["experiment_session_id"])
        session.status, session.ended_at = "completed", utc_now()
        db.commit()
    client = api_context["client"]
    first = client.post("/api/v1/student/experiment-sessions", headers=headers, json=payload)
    assert first.status_code == 201, first.text
    second = client.post("/api/v1/student/experiment-sessions", headers=headers, json=payload)
    assert second.status_code == 201
    assert first.json() == second.json()
    changed = client.post(
        "/api/v1/student/experiment-sessions",
        headers=headers,
        json={**payload, "device_id": "other-device"},
    )
    assert changed.status_code == 409


def test_end_is_idempotent_and_does_not_claim_repair(api_context):
    headers, _ = prepare(api_context)
    path = f"/api/v1/student/experiment-sessions/{api_context['experiment_session_id']}/end"
    payload = {"request_id": str(uuid4()), "expected_version": 1, "reason": "completed"}
    first = api_context["client"].post(path, headers=headers, json=payload)
    assert first.status_code == 200, first.text
    second = api_context["client"].post(path, headers=headers, json=payload)
    assert second.json() == first.json()
    assert first.json()["status"] == "completed"
    assert first.json()["version_no"] == 2
    assert (
        api_context["client"]
        .post(path, headers=headers, json={**payload, "request_id": str(uuid4())})
        .status_code
        == 409
    )


def test_formal_session_requires_published_pinned_package(api_context):
    headers, payload = prepare(api_context)
    with api_context["session_factory"]() as db:
        session = db.get(ExperimentSession, api_context["experiment_session_id"])
        session.status, session.ended_at = "completed", utc_now()
        db.get(ExperimentAssignment, session.experiment_assignment_id).is_test_data = False
        db.commit()
    response = api_context["client"].post(
        "/api/v1/student/experiment-sessions", headers=headers, json=payload
    )
    assert response.status_code == 409
