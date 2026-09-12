import json
from datetime import datetime, timezone
from typing import Any

import pytest

from app.ai.clients import AICompletion
from app.ai.schemas import AIKnowledgeReference
from app.core.config import Settings
from app.models import (
    AICallRecord,
    Device,
    DiagnosisResult,
    DiagnosisWorkflowRun,
    ExperimentSession,
)
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
                "steps": [],  # Route/cache fixture; actions are tested separately.
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
        )

        assert result.status == "failed"
        assert result.mode == "rules_only"
        assert result.explanation is None
        call = db.get(AICallRecord, result.call_record_id)
        assert call is not None
        assert call.error_code == "AI_OUTPUT_OR_PROVIDER_FAILED"


def test_graph_supplied_knowledge_is_reused_without_second_retrieval(
    api_context: dict[str, Any], monkeypatch
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
        primary = diagnosis.matched_rules[0]
        evidence_item = primary["evidence"][0]
        allowed_evidence = f"{evidence_item['fact']}: {evidence_item['observed_value']}"
        knowledge = AIKnowledgeReference(
            chunk_id="graph-kb-chunk",
            case_id="graph-kb-chunk",
            source_key="graph-kb-source",
            source_title="合成图检索来源",
            source_type="structured_case",
            source_uri=None,
            content="仅用于确认图节点检索结果被复用。",
            similarity=1.0,
            is_test_data=True,
        )
        fake = FakeAIClient(
            {
                "error_type": primary["error_type"],
                "summary": "复用图检索证据。",
                "evidence": [allowed_evidence],
                "possible_causes": [],
                "steps": [],  # Route/cache fixture; actions are tested separately.
                "hint_level": 1,
                "need_teacher_help": False,
                "limitations": ["仅为合成复用测试。"],
            }
        )
        monkeypatch.setattr(
            "app.services.ai_diagnosis._match_structured_knowledge",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(
                AssertionError("the graph retrieval result must be reused")
            ),
        )

        result = explain_diagnosis(
            db,
            device,
            diagnosis,
            settings,
            ai_client=fake,
            retrieved_knowledge=[knowledge],
        )

        assert result.status == "succeeded"
        assert result.knowledge_references[0].chunk_id == "graph-kb-chunk"


def test_workflow_ai_replay_reuses_audit_without_second_provider_call(
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
        ai_calls_per_episode=10,
        ai_calls_per_device_hour=10,
    )
    with api_context["session_factory"]() as db:
        diagnosis = db.get(DiagnosisResult, diagnosis_id)
        device = db.query(Device).one()
        experiment_session = db.query(ExperimentSession).one()
        primary = diagnosis.matched_rules[0]
        evidence_item = primary["evidence"][0]
        fake = FakeAIClient(
            {
                "error_type": primary["error_type"],
                "summary": "工作流 AI 重放只调用一次 Provider。",
                "evidence": [f"{evidence_item['fact']}: {evidence_item['observed_value']}"],
                "possible_causes": [],
                "steps": [],  # Route/cache fixture; actions are tested separately.
                "hint_level": 1,
                "need_teacher_help": False,
                "limitations": ["仅为合成幂等测试。"],
            }
        )
        workflow_id = "ai-replay-workflow"
        workflow = DiagnosisWorkflowRun(
            id=workflow_id,
            device_id=device.id,
            student_user_id=experiment_session.student_user_id,
            experiment_session_id=experiment_session.id,
            diagnosis_result_id=diagnosis.id,
            graph_thread_id=f"diagnosis:{workflow_id}",
            graph_version="test",
            status="ai_analysis",
            node_trace=[],
            node_metrics=[],
            retrieval_audit={},
            error_messages=[],
            is_test_data=True,
        )
        db.add(workflow)
        db.commit()

        first = explain_diagnosis(
            db,
            device,
            diagnosis,
            settings,
            ai_client=fake,
            workflow_run_id=workflow.id,
        )
        first_record = db.get(AICallRecord, first.call_record_id)
        first_episode = first_record.episode
        first_episode_calls = first_episode.ai_call_count
        first_audit_count = db.query(AICallRecord).count()
        first_cost = sum(item.estimated_cost or 0 for item in db.query(AICallRecord))

        second = explain_diagnosis(
            db,
            device,
            diagnosis,
            settings,
            ai_client=fake,
            workflow_run_id=workflow.id,
        )

        assert fake.calls == 1
        assert second.call_record_id == first.call_record_id
        assert db.query(AICallRecord).count() == first_audit_count == 1
        assert first_record.workflow_run_id == workflow.id
        assert first_episode.ai_call_count == first_episode_calls == 1
        assert sum(item.estimated_cost or 0 for item in db.query(AICallRecord)) == first_cost


@pytest.mark.parametrize("unlisted_step", [False, True])
def test_provider_boundary_is_applied_before_response_and_audit(api_context, unlisted_step):
    """Exercise service + real test DB, not only the private validator."""
    diagnosis_id = _create_diagnosis(api_context)
    settings = Settings(
        _env_file=None, ai_enabled=True, ai_require_knowledge=False, ai_max_retries=0
    )
    with api_context["session_factory"]() as db:
        diagnosis = db.get(DiagnosisResult, diagnosis_id)
        fake = FakeAIClient(
            {
                "error_type": diagnosis.matched_rules[0]["error_type"],
                "summary": "已确认根因是传感器损坏。",
                "evidence": [],
                "possible_causes": [],
                "steps": ["直接更换主板。"] if unlisted_step else [],
                "hint_level": 1,
                "need_teacher_help": False,
                "limitations": ["真实硬件验证通过"],
            }
        )
        result = explain_diagnosis(db, db.query(Device).one(), diagnosis, settings, ai_client=fake)
        record = db.get(AICallRecord, result.call_record_id)
        assert fake.calls == 1
        if unlisted_step:
            assert result.status == "failed"
            assert result.explanation is None
            assert result.deterministic_result["steps"]
            assert record.output_json is None
            assert record.validation_status == "failed"
        else:
            assert result.status == "succeeded"
            assert result.explanation.summary != fake.content["summary"]
            assert result.explanation.limitations != fake.content["limitations"]
            assert record.output_json == result.explanation.model_dump(mode="json")


def test_old_audit_prose_is_not_served_as_current_validated_output(api_context):
    from app.services.ai_diagnosis import serialize_ai_call

    record = AICallRecord(
        id="synthetic-old-audit",
        diagnosis_result_id="synthetic",
        status="succeeded",
        input_snapshot={},
        knowledge_references=[],
        output_json={
            "error_type": "SENSOR_READ_FAILED",
            "summary": "已确认根因是器件损坏。",
            "steps": ["直接更换主板。"],
            "hint_level": 1,
            "need_teacher_help": False,
        },
    )
    before = dict(record.output_json)
    result = serialize_ai_call(record, Settings(_env_file=None))
    assert result.status == "failed" and result.mode == "rules_only"
    assert result.explanation is None
    assert record.output_json == before  # Historical audit is not rewritten.


def test_invalid_cached_steps_are_revalidated_and_replaced(api_context):
    from app.models.ai_explanation_cache import AIExplanationCache

    diagnosis_id = _create_diagnosis(api_context)
    settings = Settings(
        _env_file=None,
        ai_enabled=True,
        ai_require_knowledge=False,
        ai_max_retries=0,
        ai_calls_per_episode=10,
        ai_calls_per_device_hour=10,
    )
    with api_context["session_factory"]() as db:
        diagnosis = db.get(DiagnosisResult, diagnosis_id)
        device = db.query(Device).one()
        fake = FakeAIClient(
            {
                "error_type": diagnosis.matched_rules[0]["error_type"],
                "summary": "合成缓存测试",
                "evidence": [],
                "possible_causes": [],
                "steps": [],
                "hint_level": 1,
                "need_teacher_help": False,
            }
        )
        first = explain_diagnosis(db, device, diagnosis, settings, ai_client=fake)
        assert first.status == "succeeded"
        cached = db.query(AIExplanationCache).one()
        cached.explanation_json = {**cached.explanation_json, "steps": ["直接更换主板。"]}
        db.commit()
        second = explain_diagnosis(db, device, diagnosis, settings, ai_client=fake)
        assert second.status == "succeeded"
        assert second.explanation.steps == []
        assert fake.calls == 2
        assert db.query(AIExplanationCache).one().explanation_json["steps"] == []
