"""XJ-012 real two-transaction export/revocation commit orders."""

from concurrent.futures import ThreadPoolExecutor
from threading import Event

import pytest
from sqlalchemy import delete, event, select, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session
from test_audit_remediation import audit_env as _audit_env
from test_audit_remediation import teacher

from app.api.v1.routes import interventions
from app.models import Classroom, TeachingAssignment, User
from app.models.classroom import AuditEvent

audit_env = _audit_env


def export_scope(env):
    headers = teacher(env)
    with env.sessions() as db:
        user = db.scalar(select(User).where(User.username == "synthetic-teacher"))
        grant = db.scalar(select(TeachingAssignment).where(TeachingAssignment.user_id == user.id))
        return headers, grant.class_id, user.id


def test_csv_revocation_commits_before_final_authorization(audit_env, monkeypatch):
    env = audit_env
    headers, class_id, user_id = export_scope(env)
    entered, release = Event(), Event()
    original = interventions._assert_teacher_class_access

    def pause(db, actor, class_id):
        original(db, actor, class_id)
        entered.set()
        assert release.wait(10)

    monkeypatch.setattr(interventions, "_assert_teacher_class_access", pause)
    with ThreadPoolExecutor(max_workers=1) as pool:
        pending = pool.submit(
            env.client.get,
            f"/api/v1/teacher-workflow/classes/{class_id}/report.csv",
            headers=headers,
        )
        try:
            assert entered.wait(10)
            with env.sessions() as revoker:
                revoker.execute(text("SET LOCAL statement_timeout='3s'"))
                revoker.execute(
                    delete(TeachingAssignment).where(
                        TeachingAssignment.user_id == user_id,
                    )
                )
                revoker.commit()
        finally:
            release.set()
        response = pending.result(timeout=10)
    with env.sessions() as db:
        audits = db.query(AuditEvent).filter_by(action="classroom.report_export").count()
    assert (response.status_code, audits) == (403, 0)
    assert "case_id,diagnosis_result_id" not in response.text


def test_csv_commit_protects_grant_and_preserves_export(audit_env):
    env = audit_env
    headers, class_id, user_id = export_scope(env)
    entered, release = Event(), Event()

    def pause(db):
        if db.get_bind() is env.engine and any(
            isinstance(item, AuditEvent) and item.action == "classroom.report_export"
            for item in db.new
        ):
            entered.set()
            assert release.wait(10)

    event.listen(Session, "before_commit", pause)
    try:
        with ThreadPoolExecutor(max_workers=1) as pool:
            pending = pool.submit(
                env.client.get,
                f"/api/v1/teacher-workflow/classes/{class_id}/report.csv",
                headers=headers,
            )
            try:
                assert entered.wait(10)
                with env.sessions() as revoker:
                    revoker.execute(text("SET LOCAL lock_timeout='100ms'"))
                    with pytest.raises(OperationalError) as failure:
                        revoker.execute(
                            delete(TeachingAssignment).where(
                                TeachingAssignment.user_id == user_id,
                            )
                        )
                    assert failure.value.orig.sqlstate == "55P03"
                    revoker.rollback()
            finally:
                release.set()
            response = pending.result(timeout=10)
    finally:
        event.remove(Session, "before_commit", pause)
    assert response.status_code == 200
    assert response.text == "case_id,diagnosis_result_id,status,assigned_teacher,test_data\r\n"
    assert response.headers["content-disposition"] == (
        f'attachment; filename="class-{class_id}-report.csv"'
    )
    with env.sessions() as revoker:
        revoker.execute(delete(TeachingAssignment).where(TeachingAssignment.user_id == user_id))
        revoker.commit()
    with env.sessions() as db:
        audit = db.query(AuditEvent).filter_by(action="classroom.report_export").one()
        assert audit.actor_user_id == user_id
        assert audit.details_json == {"format": "csv", "row_count": 0}
        assert db.get(Classroom, class_id) is not None
