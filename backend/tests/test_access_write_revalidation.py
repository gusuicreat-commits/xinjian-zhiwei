"""XJ-012: revoke after entry checks, before each final write transaction."""

import pytest
from sqlalchemy import delete, select
from test_knowledge_case_scope import _login
from test_knowledge_case_scope import case_scope as _case_scope
from test_shared_authorization import review_setup

from app.ai.diagnosis_graph import DiagnosisNodeExecutionError
from app.api.v1.routes import diagnosis as diagnosis_routes
from app.api.v1.routes import diagnosis_workflows, interventions
from app.models import AuthSession, Classroom, Device, DiagnosisResult, TeachingAssignment, User
from app.models.base import utc_now
from app.models.classroom import AuditEvent
from app.models.diagnosis_evidence import DiagnosisEvidence
from app.models.diagnosis_workflow import DiagnosisWorkflowReview
from app.models.intervention import InterventionCase, InterventionEvent

case_scope = _case_scope


def test_intervention_rechecks_session_before_creation(case_scope, monkeypatch):
    ctx = case_scope
    headers = _login(ctx["client"], "own-teacher")
    with ctx["session_factory"]() as db:
        diagnosis_id = db.scalar(select(DiagnosisResult.id))
    original = interventions.ensure_intervention_case

    def revoke(db, *args, **kwargs):
        db.commit()  # Entry checks cannot protect a later transaction.
        teacher = db.scalar(select(User).where(User.username == "own-teacher"))
        db.query(AuthSession).filter_by(user_id=teacher.id).update({"revoked_at": utc_now()})
        db.commit()
        return original(db, *args, **kwargs)

    monkeypatch.setattr(interventions, "ensure_intervention_case", revoke)
    response = ctx["client"].post(
        f"/api/v1/teacher-workflow/diagnoses/{diagnosis_id}/intervention",
        headers=headers,
    )
    with ctx["session_factory"]() as db:
        counts = (db.query(InterventionCase).count(), db.query(InterventionEvent).count())
    assert (response.status_code, counts) == (401, (0, 0))


def test_csv_rechecks_scope_before_export_audit(case_scope, monkeypatch):
    ctx = case_scope
    headers = _login(ctx["client"], "own-teacher")
    with ctx["session_factory"]() as db:
        class_id = db.scalar(select(Classroom.id).where(Classroom.code == "phase2-test-class"))
    original = interventions._assert_teacher_class_access

    def revoke(db, actor, class_id):
        original(db, actor, class_id)
        db.execute(delete(TeachingAssignment).where(TeachingAssignment.user_id == actor.id))
        db.commit()

    monkeypatch.setattr(interventions, "_assert_teacher_class_access", revoke)
    response = ctx["client"].get(
        f"/api/v1/teacher-workflow/classes/{class_id}/report.csv",
        headers=headers,
    )
    with ctx["session_factory"]() as db:
        audits = db.query(AuditEvent).filter_by(action="classroom.report_export").count()
    assert (response.status_code, audits) == (403, 0)
    assert "case_id,diagnosis_result_id" not in response.text


def test_diagnosis_rechecks_actor_inside_save(api_context, monkeypatch):
    original = diagnosis_routes.diagnose

    def revoke(context):
        with api_context["session_factory"]() as db:
            db.scalar(select(Device)).token_hash = "revoked-synthetic-token"
            db.commit()
        return original(context)

    monkeypatch.setattr(diagnosis_routes, "diagnose", revoke)
    response = api_context["client"].post(
        "/api/v1/diagnosis/devices/phase2-test-device/run",
        headers=api_context["headers"],
        json={"lookback_seconds": 60},
    )
    with api_context["session_factory"]() as db:
        counts = (db.query(DiagnosisResult).count(), db.query(DiagnosisEvidence).count())
    assert (response.status_code, counts) == (401, (0, 0))


@pytest.mark.parametrize("revoked", [True, False])
def test_review_failure_reauthorizes_before_trace(api_context, monkeypatch, revoked):
    with api_context["session_factory"]() as db:
        graph, settings, workflow, teacher, actor = review_setup(db)
        workflow_id, teacher_id = workflow.id, teacher.id
        before = (workflow.node_metrics, workflow.error_messages, workflow.state_revision)
    response = api_context["client"].post(
        "/api/v1/auth/session",
        json={"username": "guard-teacher", "password": "synthetic"},
    )
    assert response.status_code == 200
    headers = {"Authorization": "Bearer " + response.json()["access_token"]}

    def fail(*args, **kwargs):
        db = kwargs["context"].db
        db.commit()  # An intermediate graph commit releases earlier authorization locks.
        if revoked:
            with api_context["session_factory"]() as revoker:
                revoker.execute(
                    delete(TeachingAssignment).where(
                        TeachingAssignment.user_id == teacher_id,
                    )
                )
                revoker.commit()
        raise DiagnosisNodeExecutionError("persist_result", 1.0, "SyntheticFailure")

    monkeypatch.setattr(graph, "invoke", fail)
    monkeypatch.setattr(diagnosis_workflows, "_graph", lambda request: graph)
    response = api_context["client"].post(
        f"/api/v1/diagnosis-workflows/{workflow_id}/review",
        headers=headers,
        json={"action": "reject"},
    )
    with api_context["session_factory"]() as db:
        current = db.get(type(workflow), workflow_id)
        after = (current.node_metrics, current.error_messages, current.state_revision)
        assert current.status == "waiting_teacher"
        assert db.query(DiagnosisWorkflowReview).count() == 0
    if revoked:
        assert (response.status_code, after) == (403, before)
    else:
        assert response.status_code == 503
        assert "SyntheticFailure" in after[1]
        assert any(m["status"] == "failed" for m in after[0])


@pytest.mark.parametrize("username", ["own-teacher", "phase2-test-student", "scope-admin"])
def test_intervention_normal_create_and_replay_preserves_contract(case_scope, username):
    from app.models import Role
    from app.models.classroom import role_permissions
    from app.services.rbac import assign_role, ensure_rbac_catalog

    ctx = case_scope
    with ctx["session_factory"]() as db:
        if username == "scope-admin":
            roles = ensure_rbac_catalog(db)
            admin = User(
                username=username,
                display_name="Admin",
                is_test_data=True,
                password_hash=db.scalar(
                    select(User.password_hash).where(User.username == "own-teacher")
                ),
            )
            db.add(admin)
            db.flush()
            assign_role(db, admin, roles["admin"])
            # Preserve this operation's documented admin capability bypass.
            db.execute(
                delete(role_permissions).where(role_permissions.c.role_id == roles["admin"].id)
            )
            db.commit()
            assert db.scalar(select(Role.code).where(Role.id == roles["admin"].id)) == "admin"
        diagnosis_id = db.scalar(select(DiagnosisResult.id))
    headers = _login(ctx["client"], username)
    path = f"/api/v1/teacher-workflow/diagnoses/{diagnosis_id}/intervention"
    first = ctx["client"].post(path, headers=headers)
    replay = ctx["client"].post(path, headers=headers)
    assert (first.status_code, replay.status_code) == (201, 201)
    assert first.json() == replay.json()
    assert first.json()["status"] == "open"
    assert first.json()["version_no"] == 1
    with ctx["session_factory"]() as db:
        assert db.query(InterventionCase).count() == 1
        assert db.query(InterventionEvent).filter_by(action="request_help").count() == 1
