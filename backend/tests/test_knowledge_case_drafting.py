import json

import pytest

from app.ai.clients import AICompletion
from app.ai.governance import AIQuotaDenied
from app.core.config import Settings
from app.knowledge.case_drafting import (
    CaseDraftError,
    apply_ai_assisted_polish,
    generate_ai_assisted_polish,
)
from app.models import Device, DiagnosisEpisode, DiagnosisResult, ExperimentSession
from app.models.base import utc_now
from app.models.diagnosis_feedback import DiagnosisFeedback
from app.models.knowledge import KnowledgeCaseDraft
from app.services.diagnosis_episode import upsert_episode


class FakePolishClient:
    provider = "fake-polisher"
    model = "fake-case-model"
    configured = True

    def __init__(self):
        self.prompts = []

    def complete_json(self, *, system_prompt: str, user_prompt: str) -> AICompletion:
        assert "不能创造知识" in system_prompt
        assert "source_ids" in user_prompt
        self.prompts.append(user_prompt)
        return AICompletion(
            content=json.dumps(
                {
                    "title": "DHT11 读取异常排查",
                    "symptomDescription": "连续读取失败，当前没有有效数据。",
                    "teachingNote": "先按证据逐项验证，不直接确认根因。",
                    "solutionSummary": "信息不足，等待教师确认真实修复动作。",
                    "sourceIds": json.loads(user_prompt)["source_ids"],
                },
                ensure_ascii=False,
            ),
            input_tokens=100,
            output_tokens=50,
        )


def _draft() -> KnowledgeCaseDraft:
    return KnowledgeCaseDraft(
        diagnosis_result_id="diagnosis-1",
        feedback_id="feedback-1",
        experiment_type="dht11_temperature_humidity",
        error_type="SENSOR_READ_FAILED",
        fact_snapshot={"feedback_action": "resolved"},
        template_payload={
            "experimentType": "dht11_temperature_humidity",
            "errorType": "SENSOR_READ_FAILED",
            "symptom": "连续读取失败",
            "normalState": {},
            "evidence": [{"fact": "log_event_count", "observed_value": 20}],
            "possibleCauses": ["GPIO 配置错误"],
            "solutionSteps": ["核对 GPIO 配置"],
            "teacherNotes": None,
            "reviewStatus": "pending",
        },
        quality_checks=[{"check": "student_feedback_confirmed", "passed": True}],
        root_cause={"value": None, "status": "unknown", "confirmed_by": None},
        solution_record={"verified_steps": []},
        source_ids=["feedback-1"],
        allowed_ai_fields=[
            "solutionSummary",
            "sourceIds",
            "symptomDescription",
            "teachingNote",
            "title",
        ],
        facts_locked=True,
        status="draft",
        is_test_data=True,
    )


def test_ai_polish_can_change_wording_but_not_verified_facts(persisted_draft) -> None:
    db, draft = persisted_draft
    payload = dict(draft.template_payload)
    payload["symptom"] = "DHT11 连续读取失败，尚未获得有效数据。"
    payload["aiGeneratedFields"] = {
        "title": "DHT11 读取异常排查",
        "sourceIds": draft.source_ids,
    }

    result = apply_ai_assisted_polish(db, draft, payload)

    assert result.status == "quality_checked"
    assert result.polished_payload["symptom"] == payload["symptom"]
    assert result.polished_payload["evidence"] == draft.template_payload["evidence"]


def test_ai_polish_cannot_change_verified_causes(persisted_draft) -> None:
    db, draft = persisted_draft
    payload = dict(draft.template_payload)
    payload["possibleCauses"] = ["AI 新增的未知故障"]

    with pytest.raises(CaseDraftError, match="possibleCauses"):
        apply_ai_assisted_polish(db, draft, payload)


@pytest.fixture
def persisted_draft(api_context):
    with api_context["session_factory"]() as db:
        session = db.get(ExperimentSession, api_context["experiment_session_id"])
        diagnosis = DiagnosisResult(
            device_id=session.device_id,
            evaluated_at=utc_now(),
            ruleset_version="polish-test",
            ruleset_hash="1" * 64,
            input_fingerprint="2" * 64,
            experiment_id="dht11_temperature_humidity",
            matched_rules=[{"error_type": "SENSOR_READ_FAILED"}],
            evidence=[{"fact": "log_event_count", "observed_value": 20}],
            context_snapshot={"is_test_data": True},
            is_test_data=True,
        )
        db.add(diagnosis)
        db.flush()
        episode = upsert_episode(db, db.get(Device, session.device_id), diagnosis, [], Settings())
        assert episode is not None
        assert diagnosis.episode_id == episode.id
        feedback = DiagnosisFeedback(
            device_id=session.device_id,
            diagnosis_result_id=diagnosis.id,
            experiment_session_id=session.id,
            action="resolved",
            is_test_data=True,
        )
        db.add(feedback)
        db.flush()
        draft = _draft()
        draft.diagnosis_result_id = diagnosis.id
        draft.feedback_id = feedback.id
        draft.source_ids = [feedback.id]
        db.add(draft)
        db.commit()
        yield db, draft


def test_ai_polish_generates_only_expression_fields_and_saves_audit(persisted_draft) -> None:
    db, draft = persisted_draft

    result = generate_ai_assisted_polish(
        db,
        draft,
        Settings(ai_enabled=True),
        ai_client=FakePolishClient(),  # type: ignore[arg-type]
    )

    assert result.polished_payload["evidence"] == draft.template_payload["evidence"]
    assert result.polished_payload["aiGeneratedFields"]["sourceIds"] == draft.source_ids
    assert result.ai_audit["provider"] == "fake-polisher"
    assert result.ai_audit["validation_status"] == "passed"


@pytest.mark.parametrize(
    "settings_values,code",
    [
        (
            {
                "ai_daily_budget": 0,
                "ai_input_cost_per_1k_tokens": 1,
                "ai_output_cost_per_1k_tokens": 1,
            },
            "DAILY_BUDGET_LIMIT",
        ),
        ({"ai_input_token_limit": 1}, "INPUT_TOKEN_LIMIT"),
    ],
)
def test_case_polish_enforces_budget_and_input_limit_before_provider(
    persisted_draft, settings_values, code
):
    db, draft = persisted_draft
    provider = FakePolishClient()
    with pytest.raises(CaseDraftError) as caught:
        generate_ai_assisted_polish(
            db, draft, Settings(ai_enabled=True, **settings_values), ai_client=provider
        )
    assert isinstance(caught.value.__cause__, AIQuotaDenied)
    assert caught.value.__cause__.code == code
    assert provider.prompts == []
    db.refresh(draft)
    assert draft.status == "draft"
    assert draft.polished_payload is None


def test_case_polish_provider_receives_redacted_feedback_and_keeps_original(persisted_draft):
    db, draft = persisted_draft
    note = (
        "api_key=SYNTHETIC-KEY-123; password=SYNTHETIC-PASSWORD-456; "
        "教师私人备注：SYNTHETIC-NOTE-789"
    )
    draft.solution_record = {**draft.solution_record, "student_note": note}
    draft.fact_snapshot = {**draft.fact_snapshot, "teacher_private_note": "SYNTHETIC-PRIVATE-012"}
    db.commit()
    provider = FakePolishClient()
    generate_ai_assisted_polish(db, draft, Settings(ai_enabled=True), ai_client=provider)
    assert len(provider.prompts) == 1
    for secret in (
        "SYNTHETIC-KEY-123",
        "SYNTHETIC-PASSWORD-456",
        "SYNTHETIC-NOTE-789",
        "SYNTHETIC-PRIVATE-012",
    ):
        assert secret not in provider.prompts[0]
    assert json.loads(provider.prompts[0])["source_ids"] == draft.source_ids
    db.refresh(draft)
    assert draft.solution_record["student_note"] == note
    assert draft.fact_snapshot["teacher_private_note"] == "SYNTHETIC-PRIVATE-012"


@pytest.mark.parametrize("ambiguous", [False, True])
def test_case_polish_rejects_missing_or_ambiguous_legacy_episode(persisted_draft, ambiguous):
    db, draft = persisted_draft
    diagnosis = db.get(DiagnosisResult, draft.diagnosis_result_id)
    episode = db.get(DiagnosisEpisode, diagnosis.episode_id)
    diagnosis.episode_id = None
    if ambiguous:
        db.add(
            DiagnosisEpisode(
                device_id=episode.device_id,
                experiment_id=episode.experiment_id,
                primary_error_code=episode.primary_error_code,
                status=episode.status,
                started_at=episode.started_at,
                last_seen_at=episode.last_seen_at,
                latest_context_fingerprint=episode.latest_context_fingerprint,
                last_diagnosis_result_id=diagnosis.id,
            )
        )
    else:
        db.delete(episode)
    db.commit()
    provider = FakePolishClient()
    with pytest.raises(CaseDraftError) as caught:
        generate_ai_assisted_polish(db, draft, Settings(ai_enabled=True), ai_client=provider)
    assert isinstance(caught.value.__cause__, AIQuotaDenied)
    assert caught.value.__cause__.code == "EPISODE_SCOPE_UNRESOLVED"
    assert provider.prompts == []
    db.refresh(draft)
    assert draft.polished_payload is None


def test_case_polish_redacts_short_name_and_untrusted_nested_reference(persisted_draft):
    db, draft = persisted_draft
    diagnosis = db.get(DiagnosisResult, draft.diagnosis_result_id)
    diagnosis.context_snapshot = {"student_name": "李明", "is_test_data": True}
    draft.fact_snapshot = {
        **draft.fact_snapshot,
        "student_name": "李明",
        "api_key": "SYNTHETIC-NESTED-SECRET",
        "reference": {"id": "SYNTHETIC-NESTED-SECRET"},
    }
    draft.solution_record = {"student_note": "李明的读数已恢复"}
    db.commit()
    provider = FakePolishClient()
    generate_ai_assisted_polish(db, draft, Settings(ai_enabled=True), ai_client=provider)
    assert len(provider.prompts) == 1
    assert "李明" not in provider.prompts[0]
    assert "SYNTHETIC-NESTED-SECRET" not in provider.prompts[0]
    assert json.loads(provider.prompts[0])["source_ids"] == draft.source_ids


def test_case_polish_rejects_source_ids_not_bound_to_diagnosis(persisted_draft):
    db, draft = persisted_draft
    draft.source_ids = ["untrusted-external-case"]
    db.commit()
    provider = FakePolishClient()
    with pytest.raises(CaseDraftError, match="source IDs"):
        generate_ai_assisted_polish(db, draft, Settings(ai_enabled=True), ai_client=provider)
    assert provider.prompts == []
