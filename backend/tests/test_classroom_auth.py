from sqlalchemy import func, select

from app.core.security import hash_device_token, hash_password
from app.models import (
    AuditEvent,
    Classroom,
    Course,
    Device,
    DeviceBinding,
    Enrollment,
    Permission,
    Role,
    TeachingAssignment,
    User,
)
from app.services.rbac import (
    ROLE_PERMISSIONS,
    assign_role,
    ensure_rbac_catalog,
)


def _seed_identity(api_context: dict[str, object]) -> dict[str, str]:
    with api_context["session_factory"]() as db:
        roles = ensure_rbac_catalog(db)
        student = User(
            username="synthetic-student",
            display_name="合成学生",
            password_hash=hash_password("synthetic-password", iterations=1_000),
            is_test_data=True,
        )
        teacher = User(
            username="synthetic-teacher",
            display_name="合成教师",
            password_hash=hash_password("synthetic-password", iterations=1_000),
            is_test_data=True,
        )
        outsider = User(
            username="synthetic-outsider",
            display_name="合成旁观者",
            password_hash=hash_password("synthetic-password", iterations=1_000),
            is_test_data=True,
        )
        course = Course(code="SYNTH-COURSE", title="合成课程", is_test_data=True)
        hidden_device = Device(
            device_key="synthetic-hidden-device",
            display_name="合成隐藏设备",
            device_type="test-fixture",
            token_hash=hash_device_token("synthetic-hidden-token", iterations=1_000),
            metadata_json={"is_test_data": True},
        )
        db.add_all([student, teacher, outsider, course, hidden_device])
        db.flush()
        classroom = Classroom(
            course_id=course.id,
            code="SYNTH-CLASS",
            name="合成班级",
            term="test-term",
            is_test_data=True,
        )
        hidden_class = Classroom(
            course_id=course.id,
            code="HIDDEN",
            name="未分配班级",
            term="test-term",
            is_test_data=True,
        )
        db.add_all([classroom, hidden_class])
        db.flush()
        assign_role(db, student, roles["student"])
        assign_role(db, teacher, roles["teacher"])
        db.add(Enrollment(class_id=classroom.id, user_id=student.id, status="active"))
        db.add(TeachingAssignment(class_id=classroom.id, user_id=teacher.id))
        visible_device = db.scalar(
            select(Device).where(Device.device_key == "phase2-test-device")
        )
        db.add(
            DeviceBinding(
                device_id=visible_device.id,
                class_id=classroom.id,
                student_user_id=student.id,
                is_active=True,
            )
        )
        db.add(
            DeviceBinding(
                device_id=hidden_device.id,
                class_id=hidden_class.id,
                student_user_id=outsider.id,
                is_active=True,
            )
        )
        db.commit()
        return {
            "class_id": classroom.id,
            "hidden_class_id": hidden_class.id,
            "visible_device": visible_device.device_key,
            "hidden_device": hidden_device.device_key,
        }


def _login(client: object, username: str) -> dict[str, object]:
    response = client.post(
        "/api/v1/auth/session",
        json={"username": username, "password": "synthetic-password"},
    )
    assert response.status_code == 200
    return response.json()


def test_login_session_and_resource_scoped_classes(api_context: dict[str, object]) -> None:
    seeded = _seed_identity(api_context)
    client = api_context["client"]

    session = _login(client, "synthetic-student")
    headers = {"Authorization": f"Bearer {session['access_token']}"}
    me = client.get("/api/v1/auth/me", headers=headers)
    classes = client.get("/api/v1/auth/classes", headers=headers)

    assert me.status_code == 200
    assert me.json()["roles"] == ["student"]
    assert session["is_test_data"] is True
    assert [item["id"] for item in classes.json()] == [seeded["class_id"]]
    assert seeded["hidden_class_id"] not in {item["id"] for item in classes.json()}
    with api_context["session_factory"]() as db:
        assert db.scalar(select(func.count(AuditEvent.id))) == 1


def test_invalid_credentials_and_unassigned_user_are_closed(
    api_context: dict[str, object],
) -> None:
    _seed_identity(api_context)
    client = api_context["client"]
    invalid = client.post(
        "/api/v1/auth/session",
        json={"username": "synthetic-student", "password": "wrong"},
    )
    outsider = _login(client, "synthetic-outsider")
    classes = client.get(
        "/api/v1/auth/classes",
        headers={"Authorization": f"Bearer {outsider['access_token']}"},
    )

    assert invalid.status_code == 401
    assert classes.status_code == 200
    assert classes.json() == []


def test_all_seven_roles_have_separated_permissions(
    api_context: dict[str, object],
) -> None:
    with api_context["session_factory"]() as db:
        roles = ensure_rbac_catalog(db)
        db.commit()

        assert set(roles) == set(ROLE_PERMISSIONS)
        assert set(roles) == {
            "student",
            "teacher",
            "teaching_assistant",
            "admin",
            "knowledge_organizer",
            "technical_reviewer",
            "formal_approver",
        }
        assert "knowledge.review.approve" not in ROLE_PERMISSIONS["teacher"]
        assert "assignment.manage" not in ROLE_PERMISSIONS["teaching_assistant"]
        assert ROLE_PERMISSIONS["knowledge_organizer"] == {"knowledge.organize"}
        assert ROLE_PERMISSIONS["technical_reviewer"] == {
            "knowledge.review.technical"
        }
        assert ROLE_PERMISSIONS["formal_approver"] == {
            "knowledge.review.approve"
        }
        assert db.scalar(select(func.count(Permission.id))) >= 1
        assert db.scalar(select(func.count(Role.id))) == 7


def test_student_and_teacher_device_dashboards_are_resource_scoped(
    api_context: dict[str, object],
) -> None:
    seeded = _seed_identity(api_context)
    client = api_context["client"]
    student = _login(client, "synthetic-student")
    teacher = _login(client, "synthetic-teacher")
    unauthenticated = client.get("/api/v1/auth/devices")

    student_headers = {"Authorization": f"Bearer {student['access_token']}"}
    teacher_headers = {"Authorization": f"Bearer {teacher['access_token']}"}
    student_devices = client.get("/api/v1/auth/devices", headers=student_headers)
    teacher_devices = client.get("/api/v1/auth/devices", headers=teacher_headers)
    visible = client.get(
        f"/api/v1/auth/devices/{seeded['visible_device']}/dashboard",
        headers=student_headers,
    )
    student_hidden = client.get(
        f"/api/v1/auth/devices/{seeded['hidden_device']}/dashboard",
        headers=student_headers,
    )
    teacher_hidden = client.get(
        f"/api/v1/auth/devices/{seeded['hidden_device']}/dashboard",
        headers=teacher_headers,
    )

    assert unauthenticated.status_code == 401
    assert [item["device_id"] for item in student_devices.json()] == [
        seeded["visible_device"]
    ]
    assert [item["device_id"] for item in teacher_devices.json()] == [
        seeded["visible_device"]
    ]
    assert visible.status_code == 200
    assert student_hidden.status_code == 404
    assert teacher_hidden.status_code == 404
