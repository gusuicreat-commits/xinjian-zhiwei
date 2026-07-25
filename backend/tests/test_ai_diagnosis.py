import json
from datetime import datetime, timezone
from typing import Any

from app.ai.clients import AICompletion, DisabledEmbeddingClient
from app.core.config import Settings
from app.models import AICallRecord, Device, DiagnosisResult
from app.services.ai_diagnosis import explain_diagnosis


class FakeAIClient:
    provider = "phase9-test-provider"
    model = "phase9-test-model"
    configured = True

    def __init__(self, content: dict[str, Any]) -> None:
        self.content = content
        self.calls = 0

    def complete_json(self, *, system_prompt: str, user_prompt: str) -> AICompletion:
        assert "不得覆盖" in system_prompt
        assert "allowed_evidence" in user_prompt
        self.calls += 1
        return AICompletion(
            content=json.dumps(self.content, ensure_ascii=False),
            input_tokens=10,
            output_tokens=20,
        )


def _create_diagnosis(api_context: dict[str, Any]) -> str:
    client = api_context["client"]
    headers = api_context["headers"]
    now = datetime.now(timezone.utc).isoformat()
    log = client.post(
        "/api/v1/device/logs",
        headers=headers,
        json={
            "level": "error",
            "message": "explicit Phase 9 test failure",
            "event_code": "SENSOR_READ_FAILED",
            "occurred_at": now,
            "is_test_data": True,
        },
    )
    assert log.status_code == 201
    diagnosis = client.post(
        "/api/v1/diagnosis/devices/phase2-test-device/run",
        headers=headers,
        json={"lookback_seconds": 60},
    )
    assert diagnosis.status_code == 201
    return diagnosis.json()["id"]


def test_unconfigured_provider_skips_and_preserves_rule_result(
    api_context: dict[str, Any],
) -> None:
    diagnosis_id = _create_diagnosis(api_context)
    response = api_context["client"].post(
        f"/api/v1/diagnosis/results/{diagnosis_id}/ai-explanation",
        headers=api_context["headers"],
    )

    assert response.status_code == 201
    payload = response.json()
    assert payload["status"] == "skipped"
    assert payload["mode"] == "rules_only"
    assert payload["provider_configured"] is False
    assert payload["rules_preserved"] is True
    assert payload["explanation"] is None
    with api_context["session_factory"]() as db:
        call = db.query(AICallRecord).one()
        diagnosis = db.get(DiagnosisResult, diagnosis_id)
        assert call.error_code == "AI_NOT_CONFIGURED"
        assert call.attempt_count == 0
        assert diagnosis is not None
        assert diagnosis.matched_rules


def test_injected_provider_returns_validated_structured_explanation(
    api_context: dict[str, Any],
) -> None:
    diagnosis_id = _create_diagnosis(api_context)
    settings = Settings(
        ai_transport="openai-compatible",
        ai_provider="phase9-test-provider",
        ai_base_url="https://provider.invalid/v1",
        ai_model="phase9-test-model",
        ai_api_key="phase9-test-key-not-for-production",
        ai_require_knowledge=False,
        ai_max_retries=0,
    )
    with api_context["session_factory"]() as db:
        diagnosis = db.get(DiagnosisResult, diagnosis_id)
        device = db.query(Device).one()
        assert diagnosis is not None
        primary = diagnosis.matched_rules[0]
        evidence_item = primary["evidence"][0]
        allowed_evidence = f"{evidence_item['fact']}: {evidence_item['observed_value']}"
        fake = FakeAIClient(
            {
                "error_type": primary["error_type"],
                "summary": "仅对确定性测试规则进行结构化解释。",
                "evidence": [allowed_evidence],
                "possible_causes": [],
                "steps": ["继续执行现有故障树中的通用排查步骤。"],
                "hint_level": 1,
                "need_teacher_help": False,
                "limitations": ["没有正式知识资料，不能给出真实硬件结论。"],
            }
        )
        result = explain_diagnosis(
            db,
            device,
            diagnosis,
            settings,
            ai_client=fake,
            embedding_client=DisabledEmbeddingClient(),
        )

        assert result.status == "succeeded"
        assert result.mode == "ai_enhanced"
        assert result.rules_preserved is True
        assert result.explanation is not None
        assert result.explanation.error_type == primary["error_type"]
        assert fake.calls == 1
        call = db.get(AICallRecord, result.call_record_id)
        assert call is not None
        assert call.status == "succeeded"
        assert call.input_tokens == 10
        assert call.output_tokens == 20
        assert "api_key" not in json.dumps(call.input_snapshot)


def test_untrusted_ai_evidence_fails_closed(api_context: dict[str, Any]) -> None:
    diagnosis_id = _create_diagnosis(api_context)
    settings = Settings(
        ai_transport="openai-compatible",
        ai_provider="phase9-test-provider",
        ai_base_url="https://provider.invalid/v1",
        ai_model="phase9-test-model",
        ai_api_key="phase9-test-key-not-for-production",
        ai_require_knowledge=False,
        ai_max_retries=0,
    )
    with api_context["session_factory"]() as db:
        diagnosis = db.get(DiagnosisResult, diagnosis_id)
        device = db.query(Device).one()
        assert diagnosis is not None
        fake = FakeAIClient(
            {
                "error_type": diagnosis.matched_rules[0]["error_type"],
                "summary": "包含虚构证据的测试输出。",
                "evidence": ["仓库中不存在的证据"],
                "possible_causes": [],
                "steps": [],
                "hint_level": 1,
                "need_teacher_help": False,
                "limitations": [],
            }
        )
        result = explain_diagnosis(
            db,
            device,
            diagnosis,
            settings,
            ai_client=fake,
            embedding_client=DisabledEmbeddingClient(),
        )

        assert result.status == "failed"
        assert result.mode == "rules_only"
        assert result.explanation is None
        call = db.get(AICallRecord, result.call_record_id)
        assert call is not None
        assert call.error_code == "AI_OUTPUT_OR_PROVIDER_FAILED"
