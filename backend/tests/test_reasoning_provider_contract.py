import json

import pytest
from pydantic import ValidationError

from app.ai.reasoning import _fallback_reasoning, _reasoning_prompt, _validate_reasoning
from app.ai.schemas import AIReasoningResult
from app.core.config import Settings


def state(conflict=True):
    return {
        "error_type": "SENSOR_READ_FAILED",
        "evidence_conflict": conflict,
        "fault_tree_candidates": [],
        "evidence_registry": [],
    }


def response(**updates):
    return {
        "error_type": "SENSOR_READ_FAILED", "conclusion": "unknown",
        "ranked_causes": [], "summary": "证据不足。", "conflict": True, **updates,
    }


def test_schema_requires_error_type_even_when_output_is_unknown():
    payload = response()
    del payload["error_type"]
    assert "error_type" in AIReasoningResult.model_json_schema()["required"]
    with pytest.raises(ValidationError):
        AIReasoningResult.model_validate(payload)


@pytest.mark.parametrize("conflict", [True, False])
def test_prompt_delivers_rule_conflict_and_exact_error_contract(conflict):
    _, user, _, _ = _reasoning_prompt(state(conflict), settings=Settings(_env_file=None))
    payload = json.loads(user)
    assert payload["evidence_conflict"] is conflict
    error_schema = payload["output_json_schema"]["properties"]["error_type"]
    assert error_schema["const"] == "SENSOR_READ_FAILED"


def test_error_and_conflict_rejection_still_enforced():
    for payload in (response(error_type="OTHER"), response(conflict=False)):
        with pytest.raises(ValueError):
            _validate_reasoning(json.dumps(payload), state(), [])
    assert _validate_reasoning(json.dumps(response()), state(), []).conflict


def test_no_error_fallback_remains_supported():
    result = _fallback_reasoning({"error_type": None}, limitation="AI disabled")
    assert result.error_type is None
    assert result.conclusion == "unknown"


def test_new_provider_contract_has_one_cause_name_and_no_legacy_fields():
    sample = state(False)
    sample['fault_tree_candidates'] = [{'cause_id': 'pin', 'name': '引脚配置', 'evidence_refs': []}]
    _, user, _, _ = _reasoning_prompt(sample, settings=Settings(_env_file=None))
    payload = json.loads(user)
    assert payload['candidate_causes'][0]['cause'] == '引脚配置'
    assert 'name' not in payload['candidate_causes'][0]
    schema = payload['output_json_schema']
    ref = schema['properties']['ranked_causes']['items']['$ref'].split('/')[-1]
    fields = schema['$defs'][ref]['properties']
    assert set(fields) == {'cause_id', 'cause', 'support_level', 'used_evidence_ids', 'reason'}
    assert {'cause_id', 'cause', 'support_level', 'used_evidence_ids', 'reason'} <= set(
        schema['$defs'][ref]['required']
    )


def test_unprovided_limits_are_not_promoted_and_real_conflict_survives():
    result = _validate_reasoning(json.dumps(response(
        limitations=['本次案例为text_only，适用条件未核验。'],
    )), state(), [])
    assert not any('text_only' in item or '适用条件' in item for item in result.limitations)
    assert any('冲突' in item for item in result.limitations)
    assert any('未确认' in item or '未知' in item for item in result.limitations)


def test_new_calls_reject_legacy_aliases_but_historical_records_still_replay():
    sample = state(False)
    sample['fault_tree_candidates'] = [
        {'cause_id': 'pin', 'name': '引脚配置', 'evidence_refs': ['e1']}
    ]
    evidence = [{'id': 'e1', 'fact': '记录的引脚配置不一致', 'status': 'valid', 'source': 'rule'}]
    sample['evidence_registry'] = evidence
    raw = response(conclusion='ranked', conflict=False, ranked_causes=[{
        'cause_id': 'pin', 'cause': '引脚配置', 'confidence': 0.6,
        'evidence': ['e1'], 'rationale': '记录支持配置候选，实际接线未知。',
    }])
    text = json.dumps(raw)
    assert _validate_reasoning(text, sample, evidence).ranked_causes[0].cause_id == 'pin'
    with pytest.raises(ValidationError):
        _validate_reasoning(text, sample, evidence, strict_provider=True)
    raw['ranked_causes'] = [{
        'cause_id': 'pin', 'cause': '引脚配置', 'support_level': 'medium',
        'used_evidence_ids': ['e1'], 'reason': '由后端根据已校验结果生成。',
    }]
    raw["summary"] = "由后端根据已校验结果生成。"
    result = _validate_reasoning(json.dumps(raw), sample, evidence, strict_provider=True)
    assert result.conclusion == 'ranked'


def test_declared_text_only_limit_is_retained_from_trusted_context():
    sample = state(False)
    sample['knowledge_constraints'] = {'standard_fault_mappings': [{
        'case_id': 'case', 'error_type': 'SENSOR_READ_FAILED',
        'applicability': {'condition_status': 'text_only'},
    }]}
    result = _validate_reasoning(json.dumps(response(conflict=False)), sample, [])
    assert any('适用条件' in item for item in result.limitations)


def test_prompt_and_validator_agree_on_unknown_empty_ranking():
    _, user, _, _ = _reasoning_prompt(state(False), settings=Settings(_env_file=None))
    condition = json.loads(user)['output_json_schema']['allOf'][0]
    assert condition['if']['properties']['conclusion']['const'] == 'unknown'
    assert condition['then']['properties']['ranked_causes']['maxItems'] == 0
    assert condition['else']['properties']['ranked_causes']['minItems'] == 1
