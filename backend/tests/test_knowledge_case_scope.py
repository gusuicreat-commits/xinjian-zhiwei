"""HTTP authorization and review lifecycle regressions with persisted ownership."""

import json
from uuid import uuid4

import pytest

from app.ai.clients import AICompletion
from app.api.v1.routes import knowledge as knowledge_routes
from app.core.config import Settings, get_settings
from app.core.security import hash_password
from app.knowledge.case_drafting import build_case_draft
from app.main import app
from app.models import (
    Classroom,
    Device,
    DeviceBinding,
    DiagnosisResult,
    Enrollment,
    ExperimentSession,
    GuidanceHistory,
    TeachingAssignment,
    User,
)
from app.models.base import utc_now
from app.models.diagnosis_feedback import DiagnosisFeedback
from app.models.knowledge import KnowledgeCaseDraft
from app.services.diagnosis_episode import upsert_episode
from app.services.rbac import assign_role, ensure_rbac_catalog


def _login(client, username):
    response = client.post(
        "/api/v1/auth/session",
        json={
            "username": username,
            "password": "synthetic-password",
        },
    )
    assert response.status_code == 200
    return {"Authorization": "Bearer " + response.json()["access_token"]}


@pytest.fixture
def case_scope(api_context):
    with api_context["session_factory"]() as db:
        roles = ensure_rbac_catalog(db)
        session = db.get(ExperimentSession, api_context["experiment_session_id"])
        student = db.get(User, session.student_user_id)
        own_class = db.query(Classroom).filter_by(code="phase2-test-class").one()
        other_class = Classroom(
            course_id=own_class.course_id, code="other-class", name="Other class", is_test_data=True
        )
        db.add(other_class)
        actors = {}
        for role, username in [
            ("teacher", "own-teacher"),
            ("teacher", "other-teacher"),
            ("formal_approver", "global-approver"),
        ]:
            actor = User(
                username=username,
                display_name=username,
                password_hash=hash_password("synthetic-password", iterations=1000),
                is_test_data=True,
            )
            db.add(actor)
            db.flush()
            assign_role(db, actor, roles[role])
            actors[username] = actor
        assign_role(db, student, roles["student"])
        db.add(Enrollment(class_id=own_class.id, user_id=student.id, status="active"))
        db.add_all(
            [
                TeachingAssignment(class_id=own_class.id, user_id=actors["own-teacher"].id),
                TeachingAssignment(class_id=other_class.id, user_id=actors["other-teacher"].id),
                DeviceBinding(
                    device_id=session.device_id,
                    class_id=own_class.id,
                    student_user_id=student.id,
                    is_active=True,
                ),
                # A shared/reused device must not grant access to another class's old diagnosis.
                DeviceBinding(
                    device_id=session.device_id,
                    class_id=other_class.id,
                    student_user_id=student.id,
                    is_active=True,
                ),
            ]
        )
        diagnosis = DiagnosisResult(
            device_id=session.device_id,
            evaluated_at=utc_now(),
            ruleset_version="scope-test",
            ruleset_hash="1" * 64,
            input_fingerprint="2" * 64,
            experiment_id="dht11_temperature_humidity",
            matched_rules=[
                {
                    "rule_id": "scope-rule",
                    "error_type": "SENSOR_READ_FAILED",
                    "summary": "合成读取失败",
                }
            ],
            evidence=[{"fact": "read_failed", "observed_value": 5}],
            context_snapshot={
                "is_test_data": True,
                "feedback_scope": {
                    "experiment_session_id": session.id,
                    "student_user_id": student.id,
                    "device_id": session.device_id,
                },
            },
            deterministic_explanation={"steps": ["核对 GPIO 配置"]},
            is_test_data=True,
        )
        db.add(diagnosis)
        db.flush()
        guidance = GuidanceHistory(
            device_id=session.device_id,
            diagnosis_result_id=diagnosis.id,
            fault_tree_id="scope-tree",
            fault_tree_title="Scope tree",
            fault_tree_status="active",
            fault_tree_version="1",
            fault_tree_hash="3" * 64,
            first_detected_at=utc_now(),
            failure_count=1,
            anomaly_duration_seconds=1,
            hint_level=1,
            ranked_causes=[{"cause_id": "gpio_config", "title": "GPIO 配置错误"}],
            is_test_data=True,
        )
        db.add(guidance)
        db.flush()
        episode = upsert_episode(
            db, db.get(Device, session.device_id), diagnosis, [guidance], Settings()
        )
        assert episode is not None
        assert diagnosis.episode_id == episode.id
        draft_ids = []
        for with_session in (True, False):
            feedback = DiagnosisFeedback(
                request_id=str(uuid4()),
                device_id=session.device_id,
                diagnosis_result_id=diagnosis.id,
                experiment_session_id=session.id if with_session else None,
                action="resolved",
                note="合成反馈",
                is_test_data=True,
            )
            db.add(feedback)
            db.flush()
            draft = build_case_draft(db, diagnosis, feedback, [guidance])
            assert draft.status == "pending_review"
            draft_ids.append(draft.id)
    return {**api_context, "draft_id": draft_ids[0], "unscoped_draft_id": draft_ids[1]}


def _approval(case_id):
    return {
        "case_id": case_id,
        "confirmed_root_cause": "gpio_config",
        "final_solution_steps": ["核对 GPIO 配置"],
        "confirmation_note": "合成教师确认",
    }


def test_case_review_is_scoped_to_recorded_feedback_class(case_scope, monkeypatch):
    client = case_scope["client"]
    own = _login(client, "own-teacher")
    outside = _login(client, "other-teacher")
    student = _login(client, "phase2-test-student")
    global_reviewer = _login(client, "global-approver")
    draft_id = case_scope["draft_id"]
    missing_scope_id = case_scope["unscoped_draft_id"]

    def unexpected_provider(*args, **kwargs):
        pytest.fail("An unauthorized request must not reach case polishing")

    monkeypatch.setattr(knowledge_routes, "generate_ai_assisted_polish", unexpected_provider)
    assert client.get("/api/v1/knowledge/case-drafts/pending", headers=student).status_code == 403
    assert client.get("/api/v1/knowledge/case-drafts/pending", headers=outside).json() == []
    own_list = client.get("/api/v1/knowledge/case-drafts/pending", headers=own)
    assert own_list.status_code == 200
    assert [d["id"] for d in own_list.json()] == [draft_id]
    for headers, item_id in [(outside, draft_id), (own, missing_scope_id), (student, draft_id)]:
        assert (
            client.post(
                f"/api/v1/knowledge/case-drafts/{item_id}/ai-polish", headers=headers
            ).status_code
            == 403
        )
        assert (
            client.post(
                f"/api/v1/knowledge/case-drafts/{item_id}/approve",
                headers=headers,
                json=_approval("denied"),
            ).status_code
            == 403
        )
    approved = client.post(
        f"/api/v1/knowledge/case-drafts/{draft_id}/approve",
        headers=own,
        json=_approval("own-approved"),
    )
    assert approved.status_code == 200
    assert approved.json()["root_cause_status"] == "confirmed"
    # Formal approvers have an explicit global role, including legacy unscoped drafts.
    global_list = client.get("/api/v1/knowledge/case-drafts/pending", headers=global_reviewer)
    assert [d["id"] for d in global_list.json()] == [missing_scope_id]
    assert (
        client.post(
            f"/api/v1/knowledge/case-drafts/{missing_scope_id}/approve",
            headers=global_reviewer,
            json=_approval("global-approved"),
        ).status_code
        == 200
    )


class ScopePolishClient:
    configured = True
    provider = "fake"
    model = "fake-model"
    calls = 0

    def complete_json(self, *, system_prompt, user_prompt):
        self.calls += 1
        payload = json.loads(user_prompt)
        return AICompletion(
            content=json.dumps(
                {
                    **{field: choices[-1] for field, choices in
                       payload["expression_choices"].items()},
                    "sourceIds": payload["source_ids"],
                },
                ensure_ascii=False,
            ),
            input_tokens=50,
            output_tokens=50,
        )


@pytest.mark.parametrize("initial_status", ["pending_review", "quality_checked"])
def test_pending_case_polish_remains_reviewable_and_approved_draft_is_immutable(
    case_scope, monkeypatch, initial_status
):
    from app.knowledge import case_drafting

    client = case_scope["client"]
    headers = _login(client, "own-teacher")
    draft_id = case_scope["draft_id"]
    with case_scope["session_factory"]() as db:
        db.get(KnowledgeCaseDraft, draft_id).status = initial_status
        db.commit()
    provider = ScopePolishClient()
    monkeypatch.setattr(case_drafting, "build_ai_client", lambda settings: provider)
    app.dependency_overrides[get_settings] = lambda: Settings(ai_enabled=True)
    polished = client.post(f"/api/v1/knowledge/case-drafts/{draft_id}/ai-polish", headers=headers)
    assert polished.status_code == 200, polished.text
    assert polished.json()["status"] == "pending_review"
    assert provider.calls == 1
    listed = client.get("/api/v1/knowledge/case-drafts/pending", headers=headers)
    assert [d["id"] for d in listed.json()] == [draft_id]
    assert (
        client.post(
            f"/api/v1/knowledge/case-drafts/{draft_id}/approve",
            headers=headers,
            json=_approval("polished-approved"),
        ).status_code
        == 200
    )
    assert (
        client.post(
            f"/api/v1/knowledge/case-drafts/{draft_id}/ai-polish", headers=headers
        ).status_code
        == 409
    )
    assert provider.calls == 1
    with case_scope["session_factory"]() as db:
        assert db.get(KnowledgeCaseDraft, draft_id).status == "approved"
