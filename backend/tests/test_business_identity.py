"""BR-AUTH: credentials identify a person; a device token is only a demo fallback."""

from sqlalchemy import select

from app.core.security import hash_password
from app.models import Device, Enrollment, ExperimentAssignment, ExperimentSession, User
from app.services.rbac import assign_role, ensure_rbac_catalog


def account_headers(api_context, *, owner=True, enrolled=True):
    with api_context["session_factory"]() as db:
        session = db.get(ExperimentSession, api_context["experiment_session_id"])
        user = db.get(User, session.student_user_id)
        if not owner:
            user = User(
                username="another-account",
                display_name="Another student",
                password_hash=hash_password("account-password", iterations=1000),
                is_test_data=True,
            )
            db.add(user)
            db.flush()
        else:
            user.password_hash = hash_password("account-password", iterations=1000)
        assign_role(db, user, ensure_rbac_catalog(db)["student"])
        assignment = db.get(ExperimentAssignment, session.experiment_assignment_id)
        if enrolled:
            db.add(Enrollment(class_id=assignment.class_id, user_id=user.id, status="active"))
        username = user.username
        db.commit()
    response = api_context["client"].post(
        "/api/v1/auth/session", json={"username": username, "password": "account-password"}
    )
    assert response.status_code == 200
    return {
        "Authorization": f"Bearer {response.json()['access_token']}",
        "X-Device-ID": api_context["headers"]["X-Device-ID"],
        "X-Experiment-Session-ID": api_context["experiment_session_id"],
    }


def test_account_can_read_and_diagnose_without_device_secret(api_context):
    headers = account_headers(api_context)
    client = api_context["client"]
    response = client.post("/api/v1/student/session", headers=headers)
    assert response.status_code == 200, response.text
    assert response.json()["auth_mode"] == "student_account"
    assert client.get("/api/v1/student/dashboard", headers=headers).status_code == 200
    diagnosed = client.post(
        "/api/v1/diagnosis/devices/phase2-test-device/run", headers=headers, json={}
    )
    assert diagnosed.status_code == 201, diagnosed.text


def test_account_cannot_borrow_another_students_session(api_context):
    headers = account_headers(api_context, owner=False)
    response = api_context["client"].get("/api/v1/student/dashboard", headers=headers)
    assert response.status_code == 403


def test_account_requires_current_enrollment(api_context):
    headers = account_headers(api_context, enrolled=False)
    assert (
        api_context["client"].get("/api/v1/student/dashboard", headers=headers).status_code == 403
    )


def test_revoked_enrollment_blocks_existing_account_session(api_context):
    headers = account_headers(api_context)
    with api_context["session_factory"]() as db:
        db.scalar(select(Enrollment)).status = "withdrawn"
        db.commit()
    assert (
        api_context["client"].get("/api/v1/student/dashboard", headers=headers).status_code == 403
    )


def test_device_secret_does_not_authenticate_a_formal_student(api_context):
    with api_context["session_factory"]() as db:
        session = db.get(ExperimentSession, api_context["experiment_session_id"])
        session.is_test_data = False
        db.get(User, session.student_user_id).is_test_data = False
        db.commit()
    response = api_context["client"].get(
        "/api/v1/student/dashboard", headers=api_context["headers"]
    )
    assert response.status_code == 401


def test_test_label_on_device_does_not_expose_formal_session(api_context):
    with api_context["session_factory"]() as db:
        session = db.get(ExperimentSession, api_context["experiment_session_id"])
        db.get(ExperimentAssignment, session.experiment_assignment_id).is_test_data = False
        db.scalar(select(Device)).metadata_json = {"is_test_data": True}
        db.commit()
    assert (
        api_context["client"]
        .post("/api/v1/student/session", headers=api_context["headers"])
        .status_code
        == 401
    )


def test_invalid_bearer_cannot_fall_back_to_valid_device_token(api_context):
    response = api_context["client"].get(
        "/api/v1/student/dashboard",
        headers={**api_context["headers"], "Authorization": "Bearer invalid"},
    )
    assert response.status_code == 401


def test_multi_role_student_cannot_see_teacher_private_case_summary(api_context):
    from test_student_scope_r2 import _diagnose

    from app.models import InterventionCase

    diagnosis = _diagnose(api_context)
    headers = account_headers(api_context)
    with api_context["session_factory"]() as db:
        session = db.get(ExperimentSession, api_context["experiment_session_id"])
        user = db.get(User, session.student_user_id)
        assign_role(db, user, ensure_rbac_catalog(db)["teacher"])
        assignment = db.get(ExperimentAssignment, session.experiment_assignment_id)
        case = InterventionCase(
            diagnosis_result_id=diagnosis["id"],
            class_id=assignment.class_id,
            resolution_summary="teacher-only-private",
            is_test_data=True,
        )
        db.add(case)
        db.commit()
        case_id = case.id
    response = api_context["client"].get(
        f"/api/v1/teacher-workflow/interventions/{case_id}", headers=headers
    )
    assert response.status_code == 200, response.text
    assert response.json()["resolution_summary"] is None


def test_account_dashboard_never_borrows_current_device_binding(api_context):
    from app.models import DeviceBinding

    headers = account_headers(api_context, owner=False)
    with api_context["session_factory"]() as db:
        session = db.get(ExperimentSession, api_context["experiment_session_id"])
        other = db.scalar(select(User).where(User.username == "another-account"))
        assignment = db.get(ExperimentAssignment, session.experiment_assignment_id)
        db.add(
            DeviceBinding(
                device_id=session.device_id,
                class_id=assignment.class_id,
                student_user_id=other.id,
                is_active=True,
            )
        )
        db.commit()
    response = api_context["client"].get(
        "/api/v1/auth/devices/phase2-test-device/dashboard", headers=headers
    )
    assert response.status_code == 403


def test_teacher_dashboard_does_not_inherit_history_when_device_moves_class(api_context):
    from test_episode_lifecycle_r2 import log, run

    from app.models import Classroom, DeviceBinding, InterventionCase, TeachingAssignment

    headers = account_headers(api_context)
    log(api_context)
    diagnosed = run(api_context)
    with api_context["session_factory"]() as db:
        session = db.get(ExperimentSession, api_context["experiment_session_id"])
        task = db.get(ExperimentAssignment, session.experiment_assignment_id)
        old_class = db.get(Classroom, task.class_id)
        new_class = Classroom(course_id=old_class.course_id, code="moved", name="New class")
        db.add(new_class)
        db.flush()
        user = db.get(User, session.student_user_id)
        assign_role(db, user, ensure_rbac_catalog(db)["teacher"])
        db.add(TeachingAssignment(class_id=new_class.id, user_id=user.id))
        db.add(DeviceBinding(device_id=session.device_id, class_id=new_class.id, is_active=True))
        db.add(
            InterventionCase(
                diagnosis_result_id=diagnosed["id"],
                class_id=old_class.id,
                resolution_summary="old-class-private",
                is_test_data=True,
            )
        )
        db.commit()
    response = api_context["client"].get("/api/v1/teacher/dashboard", headers=headers)
    assert response.status_code == 200, response.text
    assert "old-class-private" not in response.text
    assert response.json()["anomalies"] == []
    assert response.json()["recent_logs"] == []
