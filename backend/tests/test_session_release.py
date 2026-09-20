from uuid import uuid4

from sqlalchemy import select
from test_business_issues import two_issues
from test_business_sessions import prepare

from app.core.security import hash_password
from app.models import (
    AuditEvent,
    DiagnosisEpisode,
    Enrollment,
    ExperimentAssignment,
    ExperimentSession,
    ExperimentSessionCommand,
    TeachingAssignment,
    User,
)
from app.services.rbac import assign_role, ensure_rbac_catalog


def manager(ctx, role="teacher", assigned=True):
    with ctx["session_factory"]() as db:
        user = User(
            username=str(uuid4()),
            display_name="Teacher",
            password_hash=hash_password("test-pass", iterations=1000),
            is_test_data=True,
        )
        db.add(user)
        db.flush()
        assign_role(db, user, ensure_rbac_catalog(db)[role])
        session = db.get(ExperimentSession, ctx["experiment_session_id"])
        assignment = db.get(ExperimentAssignment, session.experiment_assignment_id)
        if assigned:
            db.add(TeachingAssignment(user_id=user.id, class_id=assignment.class_id))
        db.commit()
        name = user.username
    response = ctx["client"].post(
        "/api/v1/auth/session", json={"username": name, "password": "test-pass"}
    )
    return {"Authorization": "Bearer " + response.json()["access_token"]}


def test_revoked_student_session_can_be_released_and_retried(api_context):
    student, start = prepare(api_context)
    problems = two_issues(api_context)
    teacher = manager(api_context)
    sid = api_context["experiment_session_id"]
    client = api_context["client"]
    with api_context["session_factory"]() as db:
        db.scalar(select(Enrollment)).status = "withdrawn"
        db.commit()
    listing = client.get("/api/v1/teacher/experiment-sessions", headers=teacher)
    assert listing.status_code == 200
    assert listing.json()[0]["id"] == sid
    payload = {"request_id": str(uuid4()), "expected_version": 1, "reason": "资格撤销，释放设备"}
    path = f"/api/v1/teacher/experiment-sessions/{sid}/release"
    assert client.post(path, headers=student, json=payload).status_code == 403
    first = client.post(path, headers=teacher, json=payload)
    assert first.status_code == 200, first.text
    assert first.json()["status"] == "cancelled"
    assert client.post(path, headers=teacher, json=payload).json() == first.json()
    assert (
        client.post(path, headers=teacher, json={**payload, "reason": "changed"}).status_code == 409
    )
    with api_context["session_factory"]() as db:
        session = db.get(ExperimentSession, sid)
        assert session.ended_at and session.version_no == 2
        for issue in problems["issues"]:
            assert db.get(DiagnosisEpisode, issue["id"]).status != "resolved"
        assert len(list(db.scalars(select(ExperimentSessionCommand)))) == 1
        event = db.scalar(
            select(AuditEvent).where(AuditEvent.action == "experiment_session.release")
        )
        assert event.details_json["reason"] == payload["reason"]
        db.scalar(select(Enrollment)).status = "active"
        db.commit()
    new = client.post("/api/v1/student/experiment-sessions", headers=student, json=start)
    assert new.status_code == 201
    assert new.json()["id"] != sid
    assert client.post(path, headers=teacher, json=payload).json() == first.json()
    with api_context["session_factory"]() as db:
        assert db.get(ExperimentSession, new.json()["id"]).status == "active"


def test_release_scope_and_stale_version(api_context):
    prepare(api_context)
    own = manager(api_context)
    other = manager(api_context, assigned=False)
    reviewer = manager(api_context, role="formal_approver")
    path = f"/api/v1/teacher/experiment-sessions/{api_context['experiment_session_id']}/release"
    payload = {"request_id": str(uuid4()), "expected_version": 99, "reason": "换人"}
    assert api_context["client"].post(path, headers=own, json=payload).status_code == 409
    for actor in (other, reviewer):
        assert api_context["client"].post(path, headers=actor, json=payload).status_code == 403
    assert (
        api_context["client"].get("/api/v1/teacher/experiment-sessions", headers=other).json() == []
    )
    assert (
        api_context["client"].post(path, headers=own, json={**payload, "reason": "  "}).status_code
        == 422
    )


def test_receipt_recovery_rechecks_original_class_permission(api_context):
    prepare(api_context)
    teacher = manager(api_context)
    sid = api_context["experiment_session_id"]
    path = f"/api/v1/teacher/experiment-sessions/{sid}"
    payload = {"request_id": str(uuid4()), "expected_version": 1, "reason": "交接"}
    client = api_context["client"]
    assert client.post(path + "/release", headers=teacher, json=payload).status_code == 200
    with api_context["session_factory"]() as db:
        for item in db.scalars(select(TeachingAssignment)):
            db.delete(item)
        db.commit()
    assert client.get(path, headers=teacher).status_code == 403
    assert client.post(path + "/release", headers=teacher, json=payload).status_code == 403
