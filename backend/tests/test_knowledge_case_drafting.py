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
                    **{field: choices[-1] for field, choices in
                       json.loads(user_prompt)["expression_choices"].items()},
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


def test_ai_polish_can_select_grounded_expressions_but_not_change_facts(persisted_draft) -> None:
    db, draft = persisted_draft
    payload = dict(draft.template_payload)
    payload["aiGeneratedFields"] = {
        "title": "SENSOR_READ_FAILED案例记录",
        "sourceIds": draft.source_ids,
    }

    result = apply_ai_assisted_polish(db, draft, payload, actor_context=db.info["case_actor"])

    assert result.status == "quality_checked"
    assert result.polished_payload["symptom"] == payload["symptom"]
    assert result.polished_payload["evidence"] == draft.template_payload["evidence"]


def test_ai_polish_cannot_change_verified_causes(persisted_draft) -> None:
    db, draft = persisted_draft
    payload = dict(draft.template_payload)
    payload["possibleCauses"] = ["AI 新增的未知故障"]

    with pytest.raises(CaseDraftError, match="possibleCauses"):
        apply_ai_assisted_polish(db, draft, payload, actor_context=db.info["case_actor"])


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
        from shared_write_authorization import authorize_write_fixture

        from app.models import User

        reviewer = User(
            username="case-reviewer",
            display_name="Synthetic case reviewer",
            password_hash="unused",
            is_test_data=True,
        )
        db.add(reviewer)
        authorize_write_fixture(db, reviewer, "formal_approver")
        db.info["case_actor"] = reviewer._actor_context
        yield db, draft


def test_ai_polish_generates_only_expression_fields_and_saves_audit(persisted_draft) -> None:
    db, draft = persisted_draft

    result = generate_ai_assisted_polish(
        db,
        draft,
        Settings(ai_enabled=True),
        ai_client=FakePolishClient(),  # type: ignore[arg-type]
        actor_context=db.info["case_actor"],
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
            db,
            draft,
            Settings(_env_file=None, ai_enabled=True, **settings_values),
            ai_client=provider,
            actor_context=db.info["case_actor"],
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
    generate_ai_assisted_polish(
        db,
        draft,
        Settings(ai_enabled=True),
        ai_client=provider,
        actor_context=db.info["case_actor"],
    )
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
        generate_ai_assisted_polish(
            db,
            draft,
            Settings(ai_enabled=True),
            ai_client=provider,
            actor_context=db.info["case_actor"],
        )
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
    generate_ai_assisted_polish(
        db,
        draft,
        Settings(ai_enabled=True),
        ai_client=provider,
        actor_context=db.info["case_actor"],
    )
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
        generate_ai_assisted_polish(
            db,
            draft,
            Settings(ai_enabled=True),
            ai_client=provider,
            actor_context=db.info["case_actor"],
        )
    assert provider.prompts == []


@pytest.mark.parametrize(
    'field', ['title', 'symptomDescription', 'teachingNote', 'solutionSummary']
)
def test_polish_rejects_new_claim_in_every_expression_field(persisted_draft, field):
    db, draft = persisted_draft
    before_version = draft.version_no
    payload = dict(draft.template_payload)
    payload['aiGeneratedFields'] = {
        'sourceIds': draft.source_ids,
        field: '排查驱动状态、采样频率及环境干扰。',
    }
    with pytest.raises(CaseDraftError, match='grounded'):
        apply_ai_assisted_polish(db, draft, payload, actor_context=db.info['case_actor'])
    db.refresh(draft)
    assert draft.polished_payload is None
    assert draft.version_no == before_version


@pytest.mark.parametrize('field', ['symptom', 'teacherNotes'])
def test_polish_cannot_bypass_expression_contract_through_template_fields(persisted_draft, field):
    db, draft = persisted_draft
    payload = dict(draft.template_payload)
    payload[field] = '排查驱动状态、采样频率及环境干扰。'
    payload['aiGeneratedFields'] = {'sourceIds': draft.source_ids}
    with pytest.raises(CaseDraftError, match='grounded'):
        apply_ai_assisted_polish(db, draft, payload, actor_context=db.info['case_actor'])
    db.refresh(draft)
    assert draft.polished_payload is None


@pytest.mark.parametrize('entry', ['submit', 'approve'])
def test_legacy_ungrounded_polish_cannot_progress_to_publication(persisted_draft, entry):
    from app.knowledge.case_drafting import approve_case_draft, submit_case_draft_for_review
    from app.models.knowledge import KnowledgeCase
    db, draft = persisted_draft
    draft.status = 'pending_review'
    draft.polished_payload = {**draft.template_payload, 'aiGeneratedFields': {
        'sourceIds': draft.source_ids, 'teachingNote': '排查驱动状态、采样频率及环境干扰。',
    }}
    db.commit()
    version = draft.version_no
    with pytest.raises(CaseDraftError, match='grounded'):
        if entry == 'submit':
            submit_case_draft_for_review(db, draft, actor_context=db.info['case_actor'])
        else:
            approve_case_draft(db, draft, case_id='must-not-publish', reviewer_ref='unused',
                               confirmed_root_cause='GPIO 配置错误',
                               final_solution_steps=['核对 GPIO 配置'],
                               confirmation_note='synthetic',
                               actor_context=db.info['case_actor'])
    db.refresh(draft)
    assert draft.version_no == version
    assert db.get(KnowledgeCase, 'must-not-publish') is None


def test_actual_polish_service_rejects_unprovided_teaching_claim(persisted_draft):
    class UngroundedClient(FakePolishClient):
        def complete_json(self, **kwargs):
            completion = super().complete_json(**kwargs)
            raw = json.loads(completion.content)
            raw['teachingNote'] = '排查驱动状态、采样频率及环境干扰。'
            return AICompletion(content=json.dumps(raw), input_tokens=100, output_tokens=50)
    db, draft = persisted_draft
    client = UngroundedClient()
    with pytest.raises(CaseDraftError, match='validation'):
        generate_ai_assisted_polish(db, draft, Settings(ai_enabled=True),
                                   ai_client=client, actor_context=db.info['case_actor'])
    db.refresh(draft)
    assert draft.polished_payload is None
    assert len(client.prompts) == 1
