"""Real HTTP interleavings on separate sessions; no authorization or write mocks."""

import os
from unittest.mock import patch
from uuid import uuid4

import conftest
import pytest
from sqlalchemy import create_engine, text
from test_knowledge_case_scope import ScopePolishClient, _approval, _login, case_scope

from app.core.config import Settings, get_settings
from app.knowledge import case_drafting
from app.main import app
from app.models.classroom import TeachingAssignment, User
from app.models.knowledge import KnowledgeCase, KnowledgeCaseDraft
from app.services.auth import current_actor, resolve_session


@pytest.fixture(params=["sqlite", "postgres"])
def race_scope(request):
    dsn = os.getenv("XINJIAN_EVAL_POSTGRES_DSN")
    if request.param == "postgres" and not dsn:
        pytest.skip("XINJIAN_EVAL_POSTGRES_DSN not configured")
    engine = admin = None
    if request.param == "postgres":
        schema = "case_race_" + uuid4().hex
        url = dsn.replace("postgresql://", "postgresql+psycopg://", 1)
        admin = create_engine(url)
        with admin.begin() as conn:
            conn.execute(text(f"CREATE SCHEMA {schema}"))
        engine = create_engine(url, connect_args={"options": f"-csearch_path={schema}"})
    fixture = conftest.api_context.__wrapped__()
    try:
        if engine is not None:
            with patch.object(conftest, "create_engine", return_value=engine):
                context = next(fixture)
        else:
            context = next(fixture)
        yield case_scope.__wrapped__(context)
    finally:
        try:
            next(fixture)
        except StopIteration:
            pass
        if admin is not None:
            with admin.begin() as conn:
                conn.execute(text(f"DROP SCHEMA IF EXISTS {schema} CASCADE"))
            admin.dispose()


def test_two_approval_requests_publish_only_one_case(race_scope, monkeypatch):
    ctx = race_scope
    client = ctx["client"]
    own = _login(client, "own-teacher")
    formal = _login(client, "global-approver")
    draft_id = ctx["draft_id"]
    original = case_drafting._update_draft
    responses = []
    sessions = []

    def interleave(db, draft, **kwargs):
        sessions.append(db)
        if len(sessions) == 1:
            responses.append(
                client.post(
                    f"/api/v1/knowledge/case-drafts/{draft_id}/approve",
                    headers=formal,
                    json=_approval("second"),
                )
            )
        return original(db, draft, **kwargs)

    monkeypatch.setattr(case_drafting, "_update_draft", interleave)
    first = client.post(
        f"/api/v1/knowledge/case-drafts/{draft_id}/approve", headers=own, json=_approval("first")
    )
    assert len(sessions) == 2 and sessions[0] is not sessions[1]
    assert responses[0].status_code == 200
    assert first.status_code == 409
    with ctx["session_factory"]() as db:
        cases = db.query(KnowledgeCase).all()
        assert [case.id for case in cases] == ["second"]
        assert db.get(KnowledgeCaseDraft, draft_id).reviewer_ref == cases[0].confirmed_by


@pytest.mark.parametrize("concurrent_action", ["approve", "polish", "revoke_scope"])
def test_late_polish_cannot_overwrite_review_or_new_polish(
    race_scope, monkeypatch, concurrent_action
):
    ctx = race_scope
    client = ctx["client"]
    headers = _login(client, "own-teacher")
    draft_id = ctx["draft_id"]
    state = {}

    class InterleavedProvider(ScopePolishClient):
        entered = False

        def complete_json(self, **kwargs):
            if not self.entered:
                self.entered = True
                if concurrent_action == "approve":
                    response = client.post(
                        f"/api/v1/knowledge/case-drafts/{draft_id}/approve",
                        headers=headers,
                        json=_approval("approved"),
                    )
                    assert response.status_code == 200
                elif concurrent_action == "polish":
                    response = client.post(
                        f"/api/v1/knowledge/case-drafts/{draft_id}/ai-polish", headers=headers
                    )
                    assert response.status_code == 200
                else:
                    with ctx["session_factory"]() as db:
                        teacher = db.query(User).filter_by(username="own-teacher").one()
                        db.query(TeachingAssignment).filter_by(user_id=teacher.id).delete()
                        db.commit()
                with ctx["session_factory"]() as db:
                    draft = db.get(KnowledgeCaseDraft, draft_id)
                    state["before"] = (
                        draft.status,
                        draft.quality_checks,
                        draft.polished_payload,
                        draft.ai_audit,
                    )
            return super().complete_json(**kwargs)

    monkeypatch.setattr(
        case_drafting, "build_ai_client", lambda settings: InterleavedProviderSingleton
    )
    InterleavedProviderSingleton = InterleavedProvider()
    app.dependency_overrides[get_settings] = lambda: Settings(ai_enabled=True)
    response = client.post(f"/api/v1/knowledge/case-drafts/{draft_id}/ai-polish", headers=headers)
    assert response.status_code == (403 if concurrent_action == "revoke_scope" else 409)
    with ctx["session_factory"]() as db:
        draft = db.get(KnowledgeCaseDraft, draft_id)
        assert (
            draft.status,
            draft.quality_checks,
            draft.polished_payload,
            draft.ai_audit,
        ) == state["before"]


def test_publication_insert_conflict_rolls_back_claimed_revision(race_scope, monkeypatch):
    ctx = race_scope
    client = ctx["client"]
    own = _login(client, "own-teacher")
    formal = _login(client, "global-approver")
    draft_id = ctx["draft_id"]
    other_id = ctx["unscoped_draft_id"]
    original = case_drafting._update_draft
    nested = []

    def collision(db, draft, **kwargs):
        if draft.id == draft_id:
            nested.append(
                client.post(
                    f"/api/v1/knowledge/case-drafts/{other_id}/approve",
                    headers=formal,
                    json=_approval("same-case-id"),
                )
            )
        return original(db, draft, **kwargs)

    monkeypatch.setattr(case_drafting, "_update_draft", collision)
    response = client.post(
        f"/api/v1/knowledge/case-drafts/{draft_id}/approve",
        headers=own,
        json=_approval("same-case-id"),
    )
    assert nested[0].status_code == 200
    assert response.status_code == 409
    with ctx["session_factory"]() as db:
        draft = db.get(KnowledgeCaseDraft, draft_id)
        assert draft.status == "pending_review"
        assert draft.version_no == 1
        assert draft.reviewer_ref is None
        assert draft.root_cause["status"] == "unknown"
        cases = db.query(KnowledgeCase).all()
        assert len(cases) == 1 and cases[0].source_draft_id == other_id


def test_approved_draft_cannot_be_resubmitted_or_published_twice(race_scope):
    ctx = race_scope
    client = ctx["client"]
    headers = _login(client, "own-teacher")
    draft_id = ctx["draft_id"]
    response = client.post(
        f"/api/v1/knowledge/case-drafts/{draft_id}/approve", headers=headers, json=_approval("once")
    )
    assert response.status_code == 200
    with ctx["session_factory"]() as db:
        draft = db.get(KnowledgeCaseDraft, draft_id)
        assert draft.version_no == 2
        with pytest.raises(case_drafting.CaseDraftError, match="resubmitted"):
            case_drafting.submit_case_draft_for_review(
                db,
                draft,
                actor_context=current_actor(
                    resolve_session(db, headers["Authorization"].split()[1])
                ),
            )
        assert draft.status == "approved"
        original_case = db.get(KnowledgeCase, "once")
        assert original_case.source_draft_id == draft_id
        # Model a historical case with the old source_ref and no newly added FK.
        original_case.source_draft_id = None
        draft.status = "pending_review"
        db.commit()
    denied = client.post(
        f"/api/v1/knowledge/case-drafts/{draft_id}/approve",
        headers=headers,
        json=_approval("twice"),
    )
    assert denied.status_code == 409


def test_approval_rejects_a_revision_polished_after_its_validation(race_scope, monkeypatch):
    ctx = race_scope
    client = ctx["client"]
    headers = _login(client, "own-teacher")
    draft_id = ctx["draft_id"]
    original = case_drafting._update_draft
    calls = []
    provider = ScopePolishClient()
    monkeypatch.setattr(case_drafting, "build_ai_client", lambda settings: provider)
    app.dependency_overrides[get_settings] = lambda: Settings(ai_enabled=True)

    def interleave(db, draft, **kwargs):
        calls.append(db)
        if len(calls) == 1:
            response = client.post(
                f"/api/v1/knowledge/case-drafts/{draft_id}/ai-polish", headers=headers
            )
            assert response.status_code == 200
        return original(db, draft, **kwargs)

    monkeypatch.setattr(case_drafting, "_update_draft", interleave)
    response = client.post(
        f"/api/v1/knowledge/case-drafts/{draft_id}/approve",
        headers=headers,
        json=_approval("stale-review"),
    )
    assert response.status_code == 409
    assert len(calls) == 2 and calls[0] is not calls[1]
    with ctx["session_factory"]() as db:
        draft = db.get(KnowledgeCaseDraft, draft_id)
        assert draft.status == "pending_review"
        assert draft.version_no == 2
        assert draft.polished_payload
        assert draft.reviewer_ref is None
        assert db.query(KnowledgeCase).count() == 0
