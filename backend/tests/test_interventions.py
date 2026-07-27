import pytest

from app.core.security import hash_password
from app.models import (
    Classroom,
    Course,
    Device,
    DeviceBinding,
    DiagnosisResult,
    InterventionCase,
    TeachingAssignment,
    User,
)
from app.models.base import utc_now
from app.services.interventions import InterventionConflict, apply_action, timeline
from app.services.rbac import assign_role, ensure_rbac_catalog


def test_intervention_actions_are_versioned_and_private_notes_can_be_filtered(
    api_context: dict[str, object],
) -> None:
    with api_context["session_factory"]() as db:
        teacher = User(
            username="intervention-teacher",
            display_name="合成处置教师",
            password_hash=hash_password("synthetic-password", iterations=1_000),
            is_test_data=True,
        )
        case = InterventionCase(
            diagnosis_result_id="synthetic-diagnosis",
            status="open",
            version_no=1,
            is_test_data=True,
        )
        db.add_all([teacher, case])
        db.commit()
        teacher_id = teacher.id
        case_id = case.id

    first_session = api_context["session_factory"]()
    stale_session = api_context["session_factory"]()
    try:
        first_case = first_session.get(InterventionCase, case_id)
        stale_case = stale_session.get(InterventionCase, case_id)
        teacher = first_session.get(User, teacher_id)
        stale_teacher = stale_session.get(User, teacher_id)

        claimed = apply_action(
            first_session,
            first_case,
            teacher,
            action="claim",
            expected_version=1,
            note=None,
            target_teacher_user_id=None,
            is_private=True,
        )
        assert claimed.status == "claimed"
        assert claimed.version_no == 2
        with pytest.raises(InterventionConflict):
            apply_action(
                stale_session,
                stale_case,
                stale_teacher,
                action="claim",
                expected_version=1,
                note=None,
                target_teacher_user_id=None,
                is_private=True,
            )
    finally:
        first_session.close()
        stale_session.close()

    with api_context["session_factory"]() as db:
        case = db.get(InterventionCase, case_id)
        teacher = db.get(User, teacher_id)
        noted = apply_action(
            db,
            case,
            teacher,
            action="note",
            expected_version=2,
            note="private synthetic note",
            target_teacher_user_id=None,
            is_private=True,
        )
        resolved = apply_action(
            db,
            noted,
            teacher,
            action="resolve",
            expected_version=3,
            note="synthetic resolution",
            target_teacher_user_id=None,
            is_private=False,
        )
        closed = apply_action(
            db,
            resolved,
            teacher,
            action="close",
            expected_version=4,
            note=None,
            target_teacher_user_id=None,
            is_private=True,
        )

        assert closed.status == "closed"
        assert len(timeline(db, case_id, include_private=True)) == 4
        public = timeline(db, case_id, include_private=False)
        assert [item.action for item in public] == ["resolve"]
        assert all("private synthetic note" != item.note for item in public)


def test_student_request_teacher_queue_scope_and_unconfirmed_flow(
    api_context: dict[str, object],
) -> None:
    with api_context["session_factory"]() as db:
        roles = ensure_rbac_catalog(db)
        student = User(
            username="workflow-student",
            display_name="合成处置学生",
            password_hash=hash_password("synthetic-password", iterations=1_000),
            is_test_data=True,
        )
        assigned_teacher = User(
            username="workflow-teacher",
            display_name="合成负责教师",
            password_hash=hash_password("synthetic-password", iterations=1_000),
            is_test_data=True,
        )
        outside_teacher = User(
            username="workflow-outsider",
            display_name="合成其他班教师",
            password_hash=hash_password("synthetic-password", iterations=1_000),
            is_test_data=True,
        )
        course = Course(code="WORKFLOW", title="合成处置课程", is_test_data=True)
        db.add_all([student, assigned_teacher, outside_teacher, course])
        db.flush()
        classroom = Classroom(
            course_id=course.id,
            code="WORKFLOW-A",
            name="合成处置班级",
            is_test_data=True,
        )
        db.add(classroom)
        db.flush()
        assign_role(db, student, roles["student"])
        assign_role(db, assigned_teacher, roles["teacher"])
        assign_role(db, outside_teacher, roles["teacher"])
        db.add(
            TeachingAssignment(class_id=classroom.id, user_id=assigned_teacher.id)
        )
        device = db.query(Device).filter_by(device_key="phase2-test-device").one()
        db.add(
            DeviceBinding(
                device_id=device.id,
                class_id=classroom.id,
                student_user_id=student.id,
                is_active=True,
            )
        )
        diagnosis = DiagnosisResult(
            device_id=device.id,
            evaluated_at=utc_now(),
            ruleset_version="synthetic",
            ruleset_hash="0" * 64,
            input_fingerprint="1" * 64,
            matched_rules=[{"fault_code": "SYNTHETIC"}],
            evidence=[{"kind": "synthetic-fixture"}],
            context_snapshot={"is_test_data": True},
            is_test_data=True,
        )
        db.add(diagnosis)
        db.commit()
        diagnosis_id = diagnosis.id
        original_evidence = diagnosis.evidence

    client = api_context["client"]

    def login(username: str) -> dict[str, str]:
        response = client.post(
            "/api/v1/auth/session",
            json={"username": username, "password": "synthetic-password"},
        )
        assert response.status_code == 200
        return {"Authorization": f"Bearer {response.json()['access_token']}"}

    student_headers = login("workflow-student")
    teacher_headers = login("workflow-teacher")
    outside_headers = login("workflow-outsider")
    opened = client.post(
        f"/api/v1/teacher-workflow/diagnoses/{diagnosis_id}/intervention",
        headers=student_headers,
    )
    assert opened.status_code == 201
    case = opened.json()
    case_id = case["id"]
    assert case["status"] == "open"
    assert case["class_id"] is not None

    assigned_queue = client.get(
        "/api/v1/teacher-workflow/interventions",
        headers=teacher_headers,
    )
    outside_queue = client.get(
        "/api/v1/teacher-workflow/interventions",
        headers=outside_headers,
    )
    assert [item["id"] for item in assigned_queue.json()] == [case_id]
    assert outside_queue.json() == []

    outside_claim = client.post(
        f"/api/v1/teacher-workflow/interventions/{case_id}/actions",
        headers=outside_headers,
        json={"action": "claim", "expected_version": 1},
    )
    assert outside_claim.status_code == 403
    claimed = client.post(
        f"/api/v1/teacher-workflow/interventions/{case_id}/actions",
        headers=teacher_headers,
        json={"action": "claim", "expected_version": 1},
    )
    assert claimed.status_code == 200
    unconfirmed = client.post(
        f"/api/v1/teacher-workflow/interventions/{case_id}/actions",
        headers=teacher_headers,
        json={
            "action": "mark_unconfirmed",
            "expected_version": 2,
            "note": "合成证据不足，无法确认。",
            "is_private": False,
        },
    )
    assert unconfirmed.status_code == 200
    assert unconfirmed.json()["status"] == "unconfirmed"
    student_status = client.get(
        f"/api/v1/teacher-workflow/interventions/{case_id}",
        headers=student_headers,
    )
    assert student_status.status_code == 200
    assert student_status.json()["status"] == "unconfirmed"

    with api_context["session_factory"]() as db:
        diagnosis = db.get(DiagnosisResult, diagnosis_id)
        assert diagnosis.evidence == original_evidence
