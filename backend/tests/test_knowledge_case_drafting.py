import json

import pytest

from app.ai.clients import AICompletion
from app.core.config import Settings
from app.knowledge.case_drafting import (
    CaseDraftError,
    apply_ai_assisted_polish,
    generate_ai_assisted_polish,
)
from app.models.knowledge import KnowledgeCaseDraft


class FakeSession:
    def commit(self) -> None:
        pass

    def refresh(self, _record) -> None:
        pass


class FakePolishClient:
    provider = "fake-polisher"
    model = "fake-case-model"
    configured = True

    def complete_json(self, *, system_prompt: str, user_prompt: str) -> AICompletion:
        assert "不能创造知识" in system_prompt
        assert "source_ids" in user_prompt
        return AICompletion(
            content=json.dumps(
                {
                    "title": "DHT11 读取异常排查",
                    "symptomDescription": "连续读取失败，当前没有有效数据。",
                    "teachingNote": "先按证据逐项验证，不直接确认根因。",
                    "solutionSummary": "信息不足，等待教师确认真实修复动作。",
                    "sourceIds": ["feedback-1"],
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


def test_ai_polish_can_change_wording_but_not_verified_facts() -> None:
    draft = _draft()
    payload = dict(draft.template_payload)
    payload["symptom"] = "DHT11 连续读取失败，尚未获得有效数据。"
    payload["aiGeneratedFields"] = {
        "title": "DHT11 读取异常排查",
        "sourceIds": ["feedback-1"],
    }

    result = apply_ai_assisted_polish(FakeSession(), draft, payload)  # type: ignore[arg-type]

    assert result.status == "quality_checked"
    assert result.polished_payload["symptom"] == payload["symptom"]
    assert result.polished_payload["evidence"] == draft.template_payload["evidence"]


def test_ai_polish_cannot_change_verified_causes() -> None:
    draft = _draft()
    payload = dict(draft.template_payload)
    payload["possibleCauses"] = ["AI 新增的未知故障"]

    with pytest.raises(CaseDraftError, match="possibleCauses"):
        apply_ai_assisted_polish(FakeSession(), draft, payload)  # type: ignore[arg-type]


def test_ai_polish_generates_only_expression_fields_and_saves_audit() -> None:
    draft = _draft()

    result = generate_ai_assisted_polish(
        FakeSession(),  # type: ignore[arg-type]
        draft,
        Settings(ai_enabled=True),
        ai_client=FakePolishClient(),  # type: ignore[arg-type]
    )

    assert result.polished_payload["evidence"] == draft.template_payload["evidence"]
    assert result.polished_payload["aiGeneratedFields"]["sourceIds"] == ["feedback-1"]
    assert result.ai_audit["provider"] == "fake-polisher"
    assert result.ai_audit["validation_status"] == "passed"
