"""Independent prevention cases for session revocation and failed-login work."""

from unittest.mock import patch

import pytest
from sqlalchemy import func, select
from test_classroom_auth import _login, _seed_identity
from test_memory_lifecycle import _cache, _stop, _use
from test_memory_lifecycle import memory_task as _memory_task

from app.models import AIExplanationCache, AuditEvent, AuthSession, MemoryEvent, MemoryImpactReview
from app.models.base import utc_now
from app.services.auth import AuthorizationDenied, create_session, current_actor
from app.services.memory import digest
from app.services.memory_governance import execute_cleanup, plan_cleanup, review_impact

memory_task = _memory_task


def test_logout_revokes_only_current_session_and_is_idempotent(api_context):
    _seed_identity(api_context)
    client = api_context["client"]
    first = _login(client, "synthetic-teacher")
    other = _login(client, "synthetic-teacher")
    headers = {"Authorization": "Bearer " + first["access_token"]}
    assert client.delete("/api/v1/auth/session", headers=headers).status_code == 204
    assert client.delete("/api/v1/auth/session", headers=headers).status_code == 204
    assert client.get("/api/v1/auth/me", headers=headers).status_code == 401
    assert (
        client.get(
            "/api/v1/auth/me", headers={"Authorization": "Bearer " + other["access_token"]}
        ).status_code
        == 200
    )
    with api_context["session_factory"]() as db:
        assert (
            db.scalar(
                select(func.count())
                .select_from(AuditEvent)
                .where(AuditEvent.action == "auth.logout")
            )
            == 1
        )


@pytest.mark.parametrize("username", ["absent-user", "phase2-test-student"])
def test_failed_login_does_password_verification(api_context, username):
    with api_context["session_factory"]() as db:
        with patch("app.services.auth.verify_password", return_value=False) as verify:
            assert create_session(db, username, "wrong", 8) is None
        assert verify.call_count == 1


def test_revoked_session_cannot_write_memory_review(memory_task):
    db, actor, case, diagnosis, workflow, _ = memory_task
    _use(db, case, diagnosis, workflow)
    _stop(db, actor, case)
    event = db.scalar(select(MemoryEvent))
    db.get(AuthSession, current_actor(actor).session_id).revoked_at = utc_now()
    db.commit()
    with pytest.raises(AuthorizationDenied) as denied:
        review_impact(
            db, actor, event, diagnosis, expected_version=0, decision="no_change", note="synthetic"
        )
    assert denied.value.status_code == 401
    db.rollback()
    assert db.scalar(select(func.count()).select_from(MemoryImpactReview)) == 0


def test_revoked_session_cannot_delete_cache(memory_task):
    db, actor, *_ = memory_task
    row = _cache(db)
    row_id = row.id
    plan = plan_cleanup(db, actor)
    db.get(AuthSession, current_actor(actor).session_id).revoked_at = utc_now()
    db.commit()
    with pytest.raises(AuthorizationDenied):
        execute_cleanup(db, actor, plan, expected_hash=digest(plan.targets))
    db.rollback()
    assert db.get(AIExplanationCache, row_id) is not None
    assert plan.status == "planned"


def test_disabled_account_still_verifies_password_and_issues_no_session(api_context):
    from app.models import User

    with api_context["session_factory"]() as db:
        user = db.scalar(select(User).where(User.username == "phase2-test-student"))
        user.is_active = False
        db.commit()
        before = db.query(AuthSession).count()
        with patch("app.services.auth.verify_password", return_value=True) as verify:
            assert create_session(db, user.username, "correct-but-disabled", 8) is None
        verify.assert_called_once_with("correct-but-disabled", user.password_hash)
        assert db.query(AuthSession).count() == before
