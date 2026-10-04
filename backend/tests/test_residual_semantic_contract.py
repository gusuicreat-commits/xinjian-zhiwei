"""Independent counterexamples: free prose is not an executable fact contract."""
import json
from copy import deepcopy

from app.ai.diagnosis_graph import _approved_result
from app.ai.output_contract import explanation_contract, project_reasoning
from app.ai.prompts import build_prompts
from app.ai.schemas import AIDiagnosisInput

UNSUPPORTED = "3.3V属于正常额定范围"
OUT_OF_SCOPE = "使用示波器测量并替换器件"


def reasoning():
    return {"status": "ranked", "ranked_causes": [{
        "cause_id": "c1", "cause": "供电候选", "support_level": "low",
        "used_evidence_ids": ["e1"], "reason": UNSUPPORTED,
        "rationale": UNSUPPORTED, "evidence": [UNSUPPORTED],
    }], "missing_evidence": [OUT_OF_SCOPE], "next_verification_action": OUT_OF_SCOPE}


def payload():
    return AIDiagnosisInput(
        diagnosis_result_id="diagnosis-1", anonymous_device_id="anonymous-1",
        device_state={}, logs=[], sensor_readings=[], heartbeats=[], rule_matches=[],
        fault_tree_guidance=[], knowledge=[], allowed_evidence=[], is_test_data=True,
        workflow_state={"reasoned_causes": reasoning()["ranked_causes"],
                        "possible_causes": reasoning()["ranked_causes"],
                        "reasoning_status": "ranked", "missing_evidence": [OUT_OF_SCOPE],
                        "reasoning_summary": UNSUPPORTED,
                        "next_verification_action": OUT_OF_SCOPE,
                        "allowed_verification_actions": []},
    )


def test_free_reason_and_aliases_never_survive_delivery():
    original = reasoning()
    projected = project_reasoning(original)
    assert UNSUPPORTED not in json.dumps(projected, ensure_ascii=False)
    assert original["ranked_causes"][0]["reason"] == UNSUPPORTED


def test_unlicensed_request_and_action_do_not_survive_old_record_projection():
    projected = project_reasoning(reasoning())
    assert projected["missing_evidence"] == []
    assert projected["verification_requests"] == []
    assert projected["next_verification_action"] is None


def test_explanation_limitations_do_not_republish_free_requests():
    assert OUT_OF_SCOPE not in json.dumps(explanation_contract(payload()), ensure_ascii=False)


def test_actual_prompt_excludes_free_reason_and_requests_without_mutating_input():
    value = payload()
    original = deepcopy(value.model_dump())
    _, sent, _ = build_prompts(value, "counterexample")
    assert UNSUPPORTED not in sent
    assert OUT_OF_SCOPE not in sent
    assert value.model_dump() == original


def test_checkpoint_final_candidate_alias_does_not_bypass_projection():
    value = payload().workflow_state
    result = _approved_result({**value, "reasoning_mode": "ai"})
    assert UNSUPPORTED not in json.dumps(result, ensure_ascii=False)
    assert OUT_OF_SCOPE not in json.dumps(result, ensure_ascii=False)


def test_unknown_preserves_attributed_evidence_and_licensed_action():
    result = _approved_result({
        "reasoning_status": "unknown", "reasoning_mode": "ai", "reasoned_causes": [],
        "evidence_registry": [{"id": "e-config", "fact": "配置记录：GPIO17；要求GPIO16",
                               "source": "device_report", "status": "observed"}],
        "allowed_verification_actions": [{"action_id": "config", "text": "核对配置记录"}],
        "next_verification_action": "核对配置记录",
    })["ai_reasoning"]
    assert result["status"] == "unknown"
    assert result["ranked_causes"] == []
    assert result["reported_evidence"] == [{
        "id": "e-config", "fact": "配置记录：GPIO17；要求GPIO16",
        "source": "device_report", "status": "observed",
    }]
    assert result["verification_requests"] == [
        {"text": "核对配置记录", "source": "rules", "status": "unverified"}
    ]


def test_alias_compaction_is_exact_and_never_merges_independent_ids():
    from app.ai.provider_projection import explanation_input
    value = payload()
    value.workflow_state.update(sensor_data=[{'id': 'a', 'text': 'same'}],
                                sensor_values=[{'id': 'a', 'text': 'same'}])
    sent = explanation_input(value)['workflow_state']
    assert sent['field_aliases']['sensor_values'] == 'sensor_data'
    assert sent[sent['field_aliases']['sensor_values']] == value.workflow_state['sensor_values']
    value.workflow_state['sensor_values'] = [{'id': 'b', 'text': 'same'}]
    sent = explanation_input(value)['workflow_state']
    assert sent['sensor_values'][0]['id'] == 'b'
    assert 'sensor_values' not in sent.get('field_aliases', {})


def test_schema_compaction_preserves_constraints_and_title_property():
    from app.ai.provider_projection import without_schema_titles
    original = {'title': 'Annotation', 'properties': {'title': {'type': 'string', 'minLength': 2}},
                'required': ['title'], 'additionalProperties': False}
    assert without_schema_titles(original) == {
        'properties': {'title': {'type': 'string', 'minLength': 2}},
        'required': ['title'], 'additionalProperties': False,
    }


def test_raw_validation_hides_prose_and_preserves_permitted_action():
    from app.ai.reasoning import _validate_reasoning
    state = {'error_type': 'SENSOR_READ_FAILED', 'fault_tree_candidates': [
        {'cause_id': 'c1', 'name': '供电候选', 'evidence_refs': ['e1']}],
        'allowed_verification_actions': [{'text': '核对配置记录'}]}
    evidence = [{'id': 'e1', 'fact': '3.3V', 'source': 'report', 'status': 'observed'}]
    raw = reasoning()
    raw.pop('status')
    raw.update(error_type='SENSOR_READ_FAILED', conclusion='ranked', summary=UNSUPPORTED,
               next_verification_action='核对配置记录')
    result = _validate_reasoning(json.dumps(raw), state, evidence)
    assert UNSUPPORTED not in result.model_dump_json()
    assert OUT_OF_SCOPE not in result.model_dump_json()
    assert result.next_verification_action == '核对配置记录'


def test_report_projection_redacts_secret_from_an_omitted_source_field():
    from types import SimpleNamespace

    from app.ai.evidence_projection import evidence_reports
    record = SimpleNamespace(id='e1', source_type='rule', evidence_type='rule_fact',
                             normalized_value={'kind': 'rule_fact', 'fact': 'configuration',
                                               'observed_value': 'opaque-test-value'},
                             raw_payload={'password': 'opaque-test-value'})
    result = evidence_reports([record])
    assert result[0]['id'] == 'e1'
    assert 'opaque-test-value' not in json.dumps(result)
    assert record.normalized_value['observed_value'] == 'opaque-test-value'


def test_old_extra_prose_cannot_survive_by_using_a_legacy_top_level_alias():
    original = {**reasoning(), 'limitations': [UNSUPPORTED], 'rationale': UNSUPPORTED,
                'reported_evidence': [{'id': 'forged', 'fact': UNSUPPORTED}]}
    projected = project_reasoning(original)
    assert UNSUPPORTED not in json.dumps(projected, ensure_ascii=False)
    assert projected['reported_evidence'] == []
