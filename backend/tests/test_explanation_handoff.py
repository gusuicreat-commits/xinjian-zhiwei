"""Independent counterexamples for the real two-stage API study findings."""

import json
from copy import deepcopy

import pytest

from app.ai.context_builder import prepare_explanation
from app.ai.output_contract import explanation_contract
from app.ai.schemas import AIDiagnosisInput
from app.core.config import Settings
from app.services.ai_diagnosis import _validate_explanation, serialize_ai_call


def payload(state=None):
    return AIDiagnosisInput(
        diagnosis_result_id="synthetic", anonymous_device_id="anonymous", device_state={},
        logs=[], sensor_readings=[], heartbeats=[],
        rule_matches=[{"error_type": "SENSOR_READ_FAILED"}],
        fault_tree_guidance=[{"ranked_causes": [{"title": "接线候选", "cause_id": "wiring"}],
                              "hints": [{"text": "核对已有配置记录。"}]}],
        knowledge=[], workflow_state=state or {}, allowed_evidence=["存在失败记录"],
        is_test_data=True,
    )


def output(causes):
    return {"error_type": "SENSOR_READ_FAILED", "summary": "合成", "evidence": ["存在失败记录"],
            "possible_causes": causes, "steps": [], "hint_level": 1, "need_teacher_help": False}


@pytest.mark.parametrize("state", [
    {"reasoning_status": "unknown", "reasoned_causes": []},
    {"reasoning_status": "ranked", "reasoned_causes": []},
    {"reasoned_causes": []},
])
def test_explicit_empty_reasoning_is_empty_in_generation_and_validation(state):
    data = payload(state)
    _, _, user, _ = prepare_explanation(data, Settings(_env_file=None, ai_input_token_limit=10000))
    request = json.loads(user)
    assert request["output_contract"]["allowed_causes"] == []
    assert request["output_json_schema"]["properties"]["possible_causes"]["maxItems"] == 0
    with pytest.raises(ValueError, match="outside constrained reasoning"):
        _validate_explanation(json.dumps(output([{"cause": "接线候选"}])), data)
    assert _validate_explanation(json.dumps(output([])), data).possible_causes == []


def test_ranked_support_is_shared_with_generated_contract():
    data = payload({"reasoning_status": "ranked", "reasoned_causes": [
        {"cause_id": "wiring", "cause": "接线候选", "support_level": "low"},
    ]})
    assert explanation_contract(data)["allowed_causes"] == [
        {"cause": "接线候选", "max_support_level": "low"},
    ]
    with pytest.raises(ValueError, match="support level"):
        _validate_explanation(
            json.dumps(output([{"cause": "接线候选", "support_level": "high"}])), data
        )
    assert _validate_explanation(
        json.dumps(output([{"cause": "接线候选", "support_level": "low"}])), data
    ).possible_causes[0].support_level == "low"


def test_same_title_different_causes_cannot_gain_another_candidates_support():
    data = payload({"reasoning_status": "ranked", "reasoned_causes": [
        {"cause_id": "one", "cause": "同名原因", "support_level": "low"},
        {"cause_id": "two", "cause": "同名原因", "support_level": "high"},
    ]})
    with pytest.raises(ValueError, match="outside constrained reasoning"):
        _validate_explanation(
            json.dumps(output([{"cause": "同名原因", "support_level": "high"}])), data
        )


def test_legacy_without_reasoning_has_explicit_separate_allowlist():
    data = payload()
    assert explanation_contract(data)["allowed_causes"] == [
        {"cause": "接线候选", "max_support_level": "high"},
    ]
    assert _validate_explanation(json.dumps(output([{"cause": "接线候选"}])), data)


@pytest.mark.parametrize("kind,expected", [
    ("none", "KNOWLEDGE_NOT_READY"),
    ("case_length", "KNOWLEDGE_CONTEXT_BUDGET_EXCEEDED"),
    ("prompt_budget", "KNOWLEDGE_CONTEXT_BUDGET_EXCEEDED"),
    ("required", "INPUT_TOKEN_LIMIT"),
])
def test_real_service_budget_classification_and_replay(api_context, monkeypatch, kind, expected):
    from test_ai_diagnosis import FakeAIClient, _create_diagnosis
    from test_context_construction import reference

    from app.models import AICallRecord, Device, DiagnosisResult, GuidanceHistory, KnowledgeCase
    from app.services import ai_diagnosis

    diagnosis_id = _create_diagnosis(api_context)
    refs = [] if kind in {"none", "required"} else [reference({"symptom": "合成资料" * 500})]
    monkeypatch.setattr(ai_diagnosis, "_match_structured_knowledge", lambda *a: refs)
    fake = FakeAIClient(output([]))
    settings = Settings(_env_file=None, ai_enabled=True, ai_require_knowledge=True,
                        ai_input_token_limit=20000, ai_knowledge_content_max_chars=10000)
    if kind == "case_length":
        settings = settings.model_copy(update={"ai_knowledge_content_max_chars": 200})
    with api_context["session_factory"]() as db:
        diagnosis = db.get(DiagnosisResult, diagnosis_id)
        if refs:
            db.add(KnowledgeCase(
                id="ctx-case", experiment_type="synthetic",
                error_type=diagnosis.matched_rules[0]["error_type"],
                symptom="合成资料" * 500, root_cause_status="confirmed", facts_locked=True,
                quality_check_passed=True, review_status="approved", source_ref="ctx-case",
                version="1", is_test_data=True,
            ))
            db.commit()
        if kind in {"prompt_budget", "required"}:
            from app.ai.governance import estimate_prompt_tokens

            required = ai_diagnosis._build_input(
                diagnosis, db.query(GuidanceHistory).filter_by(diagnosis_result_id=diagnosis.id)
                .order_by(GuidanceHistory.fault_tree_id).all(), [], settings,
                episode_id=None, user_question=None, workflow_state=None,
            )
            _, system, user, _ = prepare_explanation(required, settings)
            limit = estimate_prompt_tokens(system, user)
            settings = settings.model_copy(update={
                "ai_input_token_limit": limit + 200 if kind == "prompt_budget" else 100,
            })
        result = ai_diagnosis._explain_diagnosis(
            db, db.query(Device).one(), diagnosis, settings, ai_client=fake,
        )
        record = db.get(AICallRecord, result.call_record_id)
        assert record.error_code == expected
        assert record.attempt_count == 0 and fake.calls == 0
        replay = serialize_ai_call(record, settings)
        assert result.notice == replay.notice
        if expected != "KNOWLEDGE_NOT_READY":
            assert "预算" in result.notice
            assert "尚无" not in result.notice
        assert record.input_snapshot["context_manifest"]["provider_attempted"] is False


def test_old_budget_skip_is_projected_without_rewriting_audit(api_context):
    from test_ai_diagnosis import _create_diagnosis

    from app.models import AICallRecord

    diagnosis_id = _create_diagnosis(api_context)
    with api_context["session_factory"]() as db:
        record = AICallRecord(
            id="old", diagnosis_result_id=diagnosis_id, status="skipped",
            error_code="KNOWLEDGE_NOT_READY", knowledge_references=[],
            prompt_version="old", prompt_hash="synthetic",
            transport="mock", attempt_count=0, duration_ms=0, is_test_data=True,
            input_snapshot={"context_manifest": {"required_complete": True,
                "selected_ids": {"case_ids": []}, "omission_counts": {"budget_omitted": 1}}},
        )
        db.add(record)
        db.commit()
        before = deepcopy(record.input_snapshot)
        response = serialize_ai_call(record, Settings(_env_file=None))
        assert "预算" in response.notice and "尚无" not in response.notice
        assert record.error_code == "KNOWLEDGE_NOT_READY" and record.input_snapshot == before


def test_current_read_rechecks_cause_allowlist(api_context):
    from test_ai_diagnosis import FakeAIClient, _create_diagnosis

    from app.models import AICallRecord, Device, DiagnosisResult
    from app.services.ai_diagnosis import _explain_diagnosis

    diagnosis_id = _create_diagnosis(api_context)
    settings = Settings(_env_file=None, ai_enabled=True, ai_require_knowledge=False)
    with api_context["session_factory"]() as db:
        diagnosis = db.get(DiagnosisResult, diagnosis_id)
        raw = output([])
        raw["evidence"] = []
        raw["error_type"] = diagnosis.matched_rules[0]["error_type"]
        result = _explain_diagnosis(db, db.query(Device).one(), diagnosis, settings,
            ai_client=FakeAIClient(raw), workflow_state={"reasoning_status": "unknown",
                                                        "reasoned_causes": []})
        assert result.status == "succeeded"
        record = db.get(AICallRecord, result.call_record_id)
        record.output_json = {**record.output_json, "possible_causes": [{"cause": "接线候选"}]}
        db.commit()
        historical = deepcopy(record.output_json)
        assert serialize_ai_call(record, settings).mode == "rules_only"
        assert record.output_json == historical
