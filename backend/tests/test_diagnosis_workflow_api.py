from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select

from app.core.config import get_settings
from app.core.security import hash_password
from app.models import (
    Device,
    DeviceBinding,
    DiagnosisWorkflowRun,
    Enrollment,
    ExperimentSession,
    User,
)
from app.models.classroom import ExperimentAssignment
from app.services.rbac import assign_role, ensure_rbac_catalog


def _admin_headers(api_context: dict[str, Any]) -> dict[str, str]:
    with api_context["session_factory"]() as db:
        roles = ensure_rbac_catalog(db)
        admin = User(
            username="workflow-api-admin",
            display_name="合成工作流管理员",
            password_hash=hash_password("synthetic-password", iterations=1_000),
            is_test_data=True,
        )
        db.add(admin)
        db.flush()
        assign_role(db, admin, roles["admin"])
        db.commit()
    response = api_context["client"].post(
        "/api/v1/auth/session",
        json={"username": "workflow-api-admin", "password": "synthetic-password"},
    )
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def _second_student_session(api_context: dict[str, Any]) -> str:
    with api_context["session_factory"]() as db:
        device = db.scalar(select(Device).where(Device.device_key == "phase2-test-device"))
        assignment = db.scalar(select(ExperimentAssignment))
        student = User(
            username="workflow-api-second-student",
            display_name="另一合成学生",
            password_hash=hash_password("synthetic-password", iterations=1_000),
            is_test_data=True,
        )
        db.add(student)
        db.flush()
        db.add_all(
            [
                Enrollment(
                    class_id=assignment.class_id,
                    user_id=student.id,
                    status="active",
                ),
                DeviceBinding(
                    device_id=device.id,
                    class_id=assignment.class_id,
                    student_user_id=student.id,
                    experiment_assignment_id=assignment.id,
                    is_active=True,
                ),
            ]
        )
        experiment_session = ExperimentSession(
            experiment_assignment_id=assignment.id,
            student_user_id=student.id,
            device_id=device.id,
            status="active",
            started_at=datetime.now(timezone.utc),
            is_test_data=True,
        )
        db.add(experiment_session)
        db.commit()
        return experiment_session.id


def test_device_can_start_and_read_completed_workflow(api_context: dict[str, Any]) -> None:
    app = api_context["client"].app
    original = app.dependency_overrides.get(get_settings)
    app.dependency_overrides[get_settings] = lambda: get_settings().model_copy(
        update={
            "diagnosis_rag_trigger_score": 0.0,
            "diagnosis_teacher_review_score": 0.0,
        }
    )
    try:
        response = api_context["client"].post(
            "/api/v1/diagnosis-workflows/devices/phase2-test-device",
            headers=api_context["headers"],
            json={"lookback_seconds": 60},
        )
        assert response.status_code == 201
        payload = response.json()
        assert payload["status"] == "completed"
        assert payload["graph_thread_id"] == f"diagnosis:{payload['id']}"
        assert payload["diagnosis_id"] == payload["id"]
        assert payload["experiment_session_id"] == api_context["experiment_session_id"]
        assert payload["review_request"] is None
        assert payload["node_metrics"] == []
        assert payload["retrieval_audit"] == {}
        read = api_context["client"].get(
            f"/api/v1/diagnosis-workflows/{payload['id']}",
            headers=api_context["headers"],
        )
        assert read.status_code == 200
        assert read.json()["final_result"]["rules_preserved"] is True
        latest = api_context["client"].get(
            "/api/v1/diagnosis-workflows/devices/phase2-test-device/latest",
            headers=api_context["headers"],
        )
        assert latest.status_code == 200
        assert latest.json()["id"] == payload["id"]
    finally:
        if original is None:
            app.dependency_overrides.pop(get_settings, None)
        else:
            app.dependency_overrides[get_settings] = original


def test_checkpoint_business_reads_reject_cross_student_and_session(
    api_context: dict[str, Any],
) -> None:
    started = api_context["client"].post(
        "/api/v1/diagnosis-workflows/devices/phase2-test-device",
        headers=api_context["headers"],
        json={"lookback_seconds": 60},
    )
    assert started.status_code == 201
    workflow_id = started.json()["diagnosis_id"]
    other_session_id = _second_student_session(api_context)
    other_headers = {
        **api_context["headers"],
        "X-Experiment-Session-ID": other_session_id,
    }

    direct = api_context["client"].get(
        f"/api/v1/diagnosis-workflows/{workflow_id}", headers=other_headers
    )
    latest = api_context["client"].get(
        "/api/v1/diagnosis-workflows/devices/phase2-test-device/latest",
        headers=other_headers,
    )

    assert direct.status_code == 404
    assert latest.status_code == 200
    assert latest.json() is None


def test_workflow_requires_session_scope_header(api_context: dict[str, Any]) -> None:
    headers = {
        key: value
        for key, value in api_context["headers"].items()
        if key != "X-Experiment-Session-ID"
    }
    response = api_context["client"].post(
        "/api/v1/diagnosis-workflows/devices/phase2-test-device",
        headers=headers,
        json={},
    )
    assert response.status_code == 422


def test_teacher_resume_rejects_tampered_diagnosis_ownership(
    api_context: dict[str, Any],
) -> None:
    app = api_context["client"].app
    original = app.dependency_overrides.get(get_settings)
    app.dependency_overrides[get_settings] = lambda: get_settings().model_copy(
        update={
            "diagnosis_rag_trigger_score": 1.0,
            "diagnosis_teacher_review_score": 1.0,
        }
    )
    try:
        started = api_context["client"].post(
            "/api/v1/diagnosis-workflows/devices/phase2-test-device",
            headers=api_context["headers"],
            json={"lookback_seconds": 60},
        )
        assert started.status_code == 201
        workflow_id = started.json()["diagnosis_id"]
        other_session_id = _second_student_session(api_context)
        with api_context["session_factory"]() as db:
            other_session = db.get(ExperimentSession, other_session_id)
            workflow = db.get(DiagnosisWorkflowRun, workflow_id)
            workflow.student_user_id = other_session.student_user_id
            db.commit()

        reviewed = api_context["client"].post(
            f"/api/v1/diagnosis-workflows/{workflow_id}/review",
            headers=_admin_headers(api_context),
            json={"action": "approve"},
        )

        assert reviewed.status_code == 409
        assert reviewed.json()["detail"]["code"] == "DIAGNOSIS_SCOPE_INVALID"
    finally:
        if original is None:
            app.dependency_overrides.pop(get_settings, None)
        else:
            app.dependency_overrides[get_settings] = original


def test_admin_can_reject_waiting_workflow_and_duplicate_review_conflicts(
    api_context: dict[str, Any],
) -> None:
    app = api_context["client"].app
    original = app.dependency_overrides.get(get_settings)
    app.dependency_overrides[get_settings] = lambda: get_settings().model_copy(
        update={
            "diagnosis_rag_trigger_score": 1.0,
            "diagnosis_teacher_review_score": 1.0,
        }
    )
    try:
        started = api_context["client"].post(
            "/api/v1/diagnosis-workflows/devices/phase2-test-device",
            headers=api_context["headers"],
            json={"lookback_seconds": 60, "question": "请检查当前状态"},
        )
        assert started.status_code == 201
        assert started.json()["status"] == "waiting_teacher"
        workflow_id = started.json()["id"]
        headers = _admin_headers(api_context)
        reviewed = api_context["client"].post(
            f"/api/v1/diagnosis-workflows/{workflow_id}/review",
            headers=headers,
            json={"action": "reject", "comment": "合成审核驳回"},
        )
        assert reviewed.status_code == 200
        assert reviewed.json()["status"] == "rejected"
        assert reviewed.json()["final_result"] is None
        assert reviewed.json()["reviews"][0]["action"] == "reject"

        device_read = api_context["client"].get(
            f"/api/v1/diagnosis-workflows/{workflow_id}",
            headers=api_context["headers"],
        )
        assert device_read.status_code == 200
        assert device_read.json()["reviews"][0]["reviewer_user_id"] == "hidden"
        assert device_read.json()["reviews"][0]["comment"] is None
        assert device_read.json()["reviews"][0]["edited_result"] is None

        for action in ("unresolved", "resolved"):
            feedback = api_context["client"].post(
                f"/api/v1/student/diagnoses/{started.json()['diagnosis_result_id']}/feedback",
                headers=api_context["headers"],
                json={"action": action},
            )
            assert feedback.status_code == 201

        recent = api_context["client"].get(
            "/api/v1/diagnosis-workflows/review-queue/recent",
            headers=headers,
        )
        assert recent.status_code == 200
        assert [item["id"] for item in recent.json()] == [workflow_id]
        assert recent.json()[0]["reviews"][0]["comment"] == "合成审核驳回"

        metrics = api_context["client"].get(
            "/api/v1/diagnosis-workflows/metrics/summary",
            headers=headers,
        )
        assert metrics.status_code == 200
        assert metrics.json() == {
            "total": 1,
            "in_progress": 0,
            "completed": 0,
            "waiting_teacher": 0,
            "rejected": 1,
            "failed": 0,
            "reviewed": 1,
            "edit_rate": 0.0,
            "reject_rate": 1.0,
            "needs_rag_count": 1,
            "resume_count": 1,
            "average_node_duration_ms": metrics.json()["average_node_duration_ms"],
            "ai_call_count": 1,
            "ai_input_tokens": 0,
            "ai_output_tokens": 0,
            "ai_estimated_cost": 0.0,
            "student_feedback_count": 1,
            "student_resolved_count": 1,
            "student_resolution_rate": 1.0,
        }
        assert metrics.json()["average_node_duration_ms"] is not None

        duplicate = api_context["client"].post(
            f"/api/v1/diagnosis-workflows/{workflow_id}/review",
            headers=headers,
            json={"action": "approve"},
        )
        assert duplicate.status_code == 409
    finally:
        if original is None:
            app.dependency_overrides.pop(get_settings, None)
        else:
            app.dependency_overrides[get_settings] = original


def test_workflow_device_scope_and_teacher_auth_are_closed(
    api_context: dict[str, Any],
) -> None:
    mismatch = api_context["client"].post(
        "/api/v1/diagnosis-workflows/devices/another-device",
        headers=api_context["headers"],
        json={},
    )
    assert mismatch.status_code in {401, 403}
    review = api_context["client"].post(
        "/api/v1/diagnosis-workflows/missing/review",
        json={"action": "approve"},
    )
    assert review.status_code == 401
