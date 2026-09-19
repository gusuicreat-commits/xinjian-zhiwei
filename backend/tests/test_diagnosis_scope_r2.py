from datetime import datetime, timezone

import pytest
from test_student_scope_r2 import _diagnose

from app.models import AICallRecord, ExperimentSession, GuidanceHistory, User


def _replace_session(ctx):
    with ctx["session_factory"]() as db:
        old = db.get(ExperimentSession, ctx["experiment_session_id"])
        old.status = "completed"
        old.ended_at = datetime.now(timezone.utc)
        user = User(
            username="replacement-diagnosis",
            display_name="new",
            password_hash="test",
            is_active=True,
            is_test_data=True,
        )
        db.add(user)
        db.flush()
        current = ExperimentSession(
            experiment_assignment_id=old.experiment_assignment_id,
            student_user_id=user.id,
            device_id=old.device_id,
            status="active",
            started_at=datetime.now(timezone.utc),
            is_test_data=True,
        )
        db.add(current)
        db.commit()
        return current.id


def _headers(ctx, session_id=None):
    headers = {k: v for k, v in ctx["headers"].items() if k.lower() != "x-experiment-session-id"}
    if session_id:
        headers["X-Experiment-Session-ID"] = session_id
    return headers


def test_headerless_diagnosis_uses_only_unique_current_session(api_context):
    _diagnose(api_context)
    _replace_session(api_context)
    result = api_context["client"].post(
        "/api/v1/diagnosis/devices/phase2-test-device/run",
        headers=_headers(api_context),
        json={"lookback_seconds": 60},
    )
    assert result.status_code == 201
    assert "old student private detail" not in result.text
    assert all(item["error_type"] != "SENSOR_READ_FAILED" for item in result.json()["matches"])


@pytest.mark.parametrize("explicit", [False, True])
@pytest.mark.parametrize(
    "endpoint,method", [("evidence", "get"), ("guidance", "post"), ("ai-explanation", "post")]
)
def test_old_diagnosis_is_denied_before_read_or_side_effect(
    api_context,
    explicit,
    endpoint,
    method,
):
    old = _diagnose(api_context)
    session_id = _replace_session(api_context)
    with api_context["session_factory"]() as db:
        before = (db.query(AICallRecord).count(), db.query(GuidanceHistory).count())
    result = getattr(api_context["client"], method)(
        f"/api/v1/diagnosis/results/{old['id']}/{endpoint}",
        headers=_headers(api_context, session_id if explicit else None),
    )
    assert result.status_code == 403
    assert "old student private detail" not in result.text
    with api_context["session_factory"]() as db:
        assert (db.query(AICallRecord).count(), db.query(GuidanceHistory).count()) == before


def test_guidance_list_filters_old_session(api_context):
    _diagnose(api_context)
    _replace_session(api_context)
    result = api_context["client"].get(
        "/api/v1/diagnosis/devices/phase2-test-device/guidance", headers=_headers(api_context)
    )
    assert result.status_code == 200
    assert result.json() == []


@pytest.mark.parametrize("state", ["none", "ambiguous"])
def test_diagnosis_without_unique_scope_is_conflict(api_context, state):
    with api_context["session_factory"]() as db:
        old = db.get(ExperimentSession, api_context["experiment_session_id"])
        if state == "none":
            old.status = "completed"
        else:
            db.add(
                ExperimentSession(
                    experiment_assignment_id=old.experiment_assignment_id,
                    student_user_id=old.student_user_id,
                    device_id=old.device_id,
                    status="active",
                    started_at=datetime.now(timezone.utc),
                )
            )
        db.commit()
    result = api_context["client"].post(
        "/api/v1/diagnosis/devices/phase2-test-device/run",
        headers=_headers(api_context),
        json={"lookback_seconds": 60},
    )
    assert result.status_code == 409
