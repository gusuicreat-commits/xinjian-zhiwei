import json
from datetime import datetime, timezone

import pytest

from app.ai.clients import AICompletion
from app.core.config import Settings
from app.diagnosis.lightweight_schemas import DiagnosisCore
from app.models import (
    AIExplanationCache,
    Device,
    DiagnosisEpisode,
    DiagnosisResult,
)
from app.services.ai_diagnosis import explain_diagnosis
from app.services.hybrid_retrieval import hybrid_retrieve
from app.services.lightweight_diagnosis import decide_ai_policy, explanation_fingerprint


class CountingAI:
    provider = "test-provider"
    model = "test-model"
    configured = True

    def __init__(self, content: dict) -> None:
        self.content = content
        self.calls = 0

    def complete_json(self, *, system_prompt: str, user_prompt: str) -> AICompletion:
        del system_prompt, user_prompt
        self.calls += 1
        return AICompletion(content=json.dumps(self.content, ensure_ascii=False))


def _diagnose_failure(api_context: dict) -> str:
    now = datetime.now(timezone.utc).isoformat()
    response = api_context["client"].post(
        "/api/v1/device/logs",
        headers=api_context["headers"],
        json={
            "level": "error",
            "message": "Phase 9 episode test",
            "event_code": "SENSOR_READ_FAILED",
            "occurred_at": now,
            "is_test_data": True,
        },
    )
    assert response.status_code == 201
    diagnosis = api_context["client"].post(
        "/api/v1/diagnosis/devices/phase2-test-device/run",
        headers=api_context["headers"],
        json={"lookback_seconds": 60},
    )
    assert diagnosis.status_code == 201
    return diagnosis.json()["id"]


def test_diagnosis_run_produces_deterministic_result_and_aggregates_episode(
    api_context: dict,
) -> None:
    first = _diagnose_failure(api_context)
    second = _diagnose_failure(api_context)
    assert first != second
    with api_context["session_factory"]() as db:
        episodes = db.query(DiagnosisEpisode).all()
        assert len(episodes) == 1
        assert episodes[0].last_diagnosis_result_id == second
        record = db.get(DiagnosisResult, second)
        assert record is not None
        assert record.deterministic_core["primary_error_code"]
        assert record.deterministic_explanation["steps"]
        assert record.ai_enhancement["status"] == "disabled"


def test_policy_and_fingerprint_are_deterministic() -> None:
    core = DiagnosisCore(
        diagnosis_result_id="test",
        primary_error_code="SENSOR_READ_FAILED",
        summary="test",
        confidence=0.4,
        evidence=["a"],
        possible_causes=[],
        suggested_steps=[],
        hint_level=1,
        need_teacher_help=False,
        rule_ids=["r1"],
        knowledge_chunk_ids=["b", "a"],
        limitations=[],
    )
    semantic_decision = decide_ai_policy(core, Settings())
    assert semantic_decision.should_call is True
    assert semantic_decision.reason == "LOW_CONFIDENCE"
    high = core.model_copy(update={"confidence": 0.8})
    assert decide_ai_policy(high, Settings()).reason == "DETERMINISTIC_RESULT_SUFFICIENT"
    assert (
        decide_ai_policy(
            high.model_copy(update={"primary_error_code": None, "rule_ids": []}),
            Settings(),
        ).reason
        == "UNKNOWN_ANOMALY"
    )
    assert (
        "MULTIPLE_RULES"
        in decide_ai_policy(high.model_copy(update={"rule_ids": ["r1", "r2"]}), Settings()).reason
    )
    assert decide_ai_policy(high, Settings(), user_question="为什么").reason == "USER_QUESTION"
    assert (
        decide_ai_policy(high, Settings(), teacher_draft_requested=True).reason
        == "TEACHER_DRAFT_REQUEST"
    )
    configured = Settings(
        ai_transport="openai-compatible",
        ai_provider="test",
        ai_base_url="https://invalid.example/v1",
        ai_model="test",
        ai_api_key="test-only",
    )
    assert decide_ai_policy(core, configured).reason == "LOW_CONFIDENCE"
    left = explanation_fingerprint(
        core,
        prompt_version="p1",
        schema_version="s1",
        ruleset_version="r1",
        fault_tree_version="f1",
        knowledge_chunk_ids=["b", "a"],
    )
    right = explanation_fingerprint(
        core.model_copy(update={"diagnosis_result_id": "another-database-id"}),
        prompt_version="p1",
        schema_version="s1",
        ruleset_version="r1",
        fault_tree_version="f1",
        knowledge_chunk_ids=["a", "b"],
    )
    assert left == right
    mutations = [
        {"ruleset_version": "r2"},
        {"fault_tree_version": "f2"},
        {"knowledge_chunk_ids": ["different"]},
        {"prompt_version": "p2"},
        {"output_language": "en-US"},
    ]
    for mutation in mutations:
        values = {
            "prompt_version": "p1",
            "schema_version": "s1",
            "ruleset_version": "r1",
            "fault_tree_version": "f1",
            "knowledge_chunk_ids": ["a", "b"],
            "output_language": "zh-CN",
        }
        values.update(mutation)
        assert explanation_fingerprint(core, **values) != left
    assert (
        explanation_fingerprint(
            core.model_copy(update={"hint_level": 2}),
            prompt_version="p1",
            schema_version="s1",
            ruleset_version="r1",
            fault_tree_version="f1",
            knowledge_chunk_ids=["a", "b"],
        )
        != left
    )


def test_hybrid_retrieval_is_disabled_for_the_mvp() -> None:
    with pytest.raises(RuntimeError, match="outside the MVP"):
        hybrid_retrieve()


def test_ai_explanation_cache_prevents_duplicate_provider_call(
    api_context: dict,
) -> None:
    diagnosis_id = _diagnose_failure(api_context)
    settings = Settings(
        ai_transport="openai-compatible",
        ai_provider="test-provider",
        ai_base_url="https://invalid.example/v1",
        ai_model="test-model",
        ai_api_key="test-only",
        ai_require_knowledge=False,
        ai_max_retries=0,
    )
    with api_context["session_factory"]() as db:
        diagnosis = db.get(DiagnosisResult, diagnosis_id)
        assert diagnosis is not None
        match = diagnosis.matched_rules[0]
        evidence = match["evidence"][0]
        fake = CountingAI(
            {
                "error_type": match["error_type"],
                "summary": "cached explanation",
                "evidence": [f"{evidence['fact']}: {evidence['observed_value']}"],
                "possible_causes": [],
                "steps": [],  # Route/cache fixture; actions are tested separately.
                "hint_level": 1,
                "need_teacher_help": False,
                "limitations": ["test-only"],
            }
        )
        real_device = db.query(Device).one()
        first = explain_diagnosis(
            db,
            real_device,
            diagnosis,
            settings,
            ai_client=fake,
        )
        second = explain_diagnosis(
            db,
            real_device,
            diagnosis,
            settings,
            ai_client=fake,
        )
        assert first.enhancement_status == "cloud_success"
        assert second.enhancement_status == "cache_hit"
        assert fake.calls == 1
        assert db.query(AIExplanationCache).count() == 1
        cache = db.query(AIExplanationCache).one()
        assert cache.hit_count == 1
