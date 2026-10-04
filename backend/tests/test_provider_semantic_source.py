"""Provider proposals cannot supply free prose even if final projection is safe."""
import json
from copy import deepcopy

import pytest
from pydantic import ValidationError

from app.ai.prompts import build_prompts
from app.ai.reasoning import _reasoning_prompt, _validate_reasoning
from app.ai.schemas import AIDiagnosisInput

PLACEHOLDER = "由后端根据已校验结果生成。"
UNSUPPORTED = "实际接线已经正常，必须使用示波器排查。"


def sample():
    evidence = [{"id": "e1", "fact": "合成配置记录不一致", "source": "rule", "status": "valid"}]
    state = {"error_type": "PIN_MISMATCH", "evidence_registry": evidence,
             "fault_tree_candidates": [{"cause_id": "c1", "name": "配置候选",
                                        "evidence_refs": ["e1"]}]}
    raw = {"error_type": "PIN_MISMATCH", "conclusion": "ranked", "ranked_causes": [{
        "cause_id": "c1", "cause": "配置候选", "support_level": "low",
        "used_evidence_ids": ["e1"], "reason": PLACEHOLDER,
    }], "summary": PLACEHOLDER, "limitations": [], "missing_evidence": [],
        "next_verification_action": None, "conflict": False}
    return state, evidence, raw


@pytest.mark.parametrize("field", ["reason", "summary", "limitations", "missing_evidence"])
def test_new_provider_rejects_free_prose_at_source(field):
    state, evidence, raw = sample()
    if field == "reason":
        raw["ranked_causes"][0][field] = UNSUPPORTED
    else:
        raw[field] = [UNSUPPORTED] if field in {"limitations", "missing_evidence"} else UNSUPPORTED
    with pytest.raises(ValidationError):
        _validate_reasoning(json.dumps(raw), state, evidence, strict_provider=True)


def test_historical_free_prose_still_replays_safely_without_mutation():
    state, evidence, raw = sample()
    raw["summary"] = raw["ranked_causes"][0]["reason"] = UNSUPPORTED
    raw["limitations"] = raw["missing_evidence"] = [UNSUPPORTED]
    original = deepcopy(raw)
    result = _validate_reasoning(json.dumps(raw), state, evidence)
    assert result.conclusion == "ranked"
    assert UNSUPPORTED not in result.model_dump_json()
    assert raw == original


@pytest.mark.parametrize("unknown", [True, False])
def test_current_provider_still_accepts_ranked_and_unknown(unknown):
    state, evidence, raw = sample()
    if unknown:
        raw.update(conclusion="unknown", ranked_causes=[])
    result = _validate_reasoning(json.dumps(raw), state, evidence, strict_provider=True)
    assert result.conclusion == ("unknown" if unknown else "ranked")
    assert PLACEHOLDER not in result.model_dump_json()


def test_reasoning_wire_schema_closes_all_free_prose_fields():
    state, _, _ = sample()
    _, user, _, _ = _reasoning_prompt(state)
    schema = json.loads(user)["output_json_schema"]
    assert schema["properties"]["summary"]["const"] == PLACEHOLDER
    for field in ("limitations", "missing_evidence"):
        assert schema["properties"][field]["maxItems"] == 0
    ref = schema["properties"]["ranked_causes"]["items"]["$ref"].split("/")[-1]
    assert schema["$defs"][ref]["properties"]["reason"]["const"] == PLACEHOLDER


def test_explanation_wire_schema_requires_exact_server_prose():
    payload = AIDiagnosisInput(
        diagnosis_result_id="synthetic", anonymous_device_id="synthetic",
        device_state={}, logs=[], sensor_readings=[], heartbeats=[], rule_matches=[],
        fault_tree_guidance=[], knowledge=[], allowed_evidence=[], is_test_data=True,
    )
    _, user, _ = build_prompts(payload, "test-source-contract")
    doc = json.loads(user)
    props = doc["output_json_schema"]["properties"]
    for field in ("summary", "limitations"):
        assert props[field]["const"] == doc["output_contract"][field]


@pytest.mark.parametrize("kind", ["foreign_evidence", "foreign_action", "conflict", "ranked_empty"])
def test_strict_prose_contract_cannot_bypass_evidence_action_or_conflict_guard(kind):
    state, evidence, raw = sample()
    if kind == "foreign_evidence":
        raw["ranked_causes"][0]["used_evidence_ids"] = ["not-in-current-diagnosis"]
    elif kind == "foreign_action":
        raw["next_verification_action"] = "更换未许可器件"
    elif kind == "conflict":
        state["evidence_conflict"] = True
    else:
        raw["ranked_causes"] = []
    with pytest.raises(ValueError):
        _validate_reasoning(json.dumps(raw), state, evidence, strict_provider=True)


@pytest.mark.parametrize("mode", ["unknown", "valid"])
def test_application_scripted_provider_obeys_current_contract(mode):
    from app.evaluation.workflow_environment import ScriptedProvider

    state, evidence, _ = sample()
    system, user, _, _ = _reasoning_prompt(state)
    completion = ScriptedProvider(mode).complete_json(system_prompt=system, user_prompt=user)
    result = _validate_reasoning(completion.content, state, evidence, strict_provider=True)
    assert result.conclusion == ("unknown" if mode == "unknown" else "ranked")


def test_current_cause_name_is_exact_but_history_is_normalized():
    state, evidence, raw = sample()
    raw["ranked_causes"][0]["cause"] = UNSUPPORTED
    replay = _validate_reasoning(json.dumps(raw), state, evidence)
    assert replay.ranked_causes[0].cause == "配置候选"
    with pytest.raises(ValueError, match="candidate name"):
        _validate_reasoning(json.dumps(raw), state, evidence, strict_provider=True)


@pytest.mark.parametrize("tampered", [False, True])
@pytest.mark.parametrize("replay_denied", [False, True])
def test_service_validates_actual_clean_name_and_never_reintroduces_secret(
    api_context, tampered, replay_denied, monkeypatch,
):
    from langgraph.checkpoint.memory import InMemorySaver
    from shared_student_authorization import demo_student_actor
    from test_r2_provider_data_boundary import _post_failure

    from app.ai.clients import AICompletion
    from app.ai.diagnosis_graph import build_diagnosis_graph
    from app.ai.reasoning import reason_about_causes
    from app.core.config import Settings
    from app.diagnosis.workflow_schemas import DiagnosisWorkflowStartRequest
    from app.models import AICallRecord, Device, DiagnosisResult
    from app.services.diagnosis_workflow import start_workflow

    secret = "synthetic-private-name-value"
    captured = []

    class Echo:
        configured = True
        provider = "synthetic"
        model = "name-echo"

        def complete_json(self, *, system_prompt, user_prompt):
            captured.append(user_prompt)
            doc = json.loads(user_prompt)
            cause = doc["candidate_causes"][0]
            return AICompletion(content=json.dumps({
                "error_type": doc["error_type"], "conclusion": "ranked",
                "ranked_causes": [{"cause_id": cause["cause_id"],
                                   "cause": "未经许可的名称" if tampered else cause["cause"],
                                   "support_level": "low",
                                   "used_evidence_ids": cause["evidence_refs"][:1],
                                   "reason": PLACEHOLDER}],
                "summary": PLACEHOLDER, "limitations": [], "missing_evidence": [],
                "conflict": False,
            }))

    _post_failure(api_context)
    graph = build_diagnosis_graph(InMemorySaver())
    with api_context["session_factory"]() as db:
        device = db.query(Device).one()
        workflow = start_workflow(
            db, graph, device,
            Settings(_env_file=None, ai_enabled=False, diagnosis_teacher_review_score=0),
            DiagnosisWorkflowStartRequest(lookback_seconds=60),
            student_actor=demo_student_actor(db, device),
        )
        state = dict(graph.get_state({"configurable": {
            "thread_id": workflow.graph_thread_id,
        }}).values)
        state["fault_tree_candidates"][0]["name"] = f"引脚 {secret} 配置"
        state["knowledge_constraints"] = {}
        diagnosis = db.get(DiagnosisResult, state["diagnosis_result_id"])
        settings = Settings(_env_file=None, ai_enabled=True, ai_require_knowledge=False,
                            ai_max_retries=0, ai_input_token_limit=20000)

        def run():
            return reason_about_causes(
                db, diagnosis, state, settings, workflow_run_id=workflow.id,
                call_stage="reasoning:clean-name", ai_client=Echo(),
                sensitive_sources=({"api_key": secret},),
            )

        result, mode = run()
        assert len(captured) == 1
        assert secret not in captured[0]
        assert mode == ("deterministic_fallback" if tampered else "ai")
        assert secret not in result.model_dump_json()
        assert "未经许可的名称" not in result.model_dump_json()
        record = db.query(AICallRecord).filter_by(call_stage="reasoning:clean-name").one()
        assert secret not in json.dumps(record.output_json)
        assert secret not in json.dumps(record.input_snapshot)
        if replay_denied:
            monkeypatch.setattr("app.ai.reasoning.current_context_policy", lambda _: False)
        replay, replay_mode = run()
        assert len(captured) == 1
        assert replay_mode == ("deterministic_fallback" if replay_denied else mode)
        assert secret not in replay.model_dump_json()
        assert replay.ranked_causes[0].cause == result.ranked_causes[0].cause
        payload = AIDiagnosisInput(
            diagnosis_result_id="synthetic", anonymous_device_id="synthetic",
            device_state={}, logs=[], sensor_readings=[], heartbeats=[], rule_matches=[],
            fault_tree_guidance=[], knowledge=[], allowed_evidence=[], is_test_data=True,
            workflow_state={"reasoned_causes": result.model_dump()["ranked_causes"],
                            "reasoning_status": result.conclusion},
        )
        assert secret not in build_prompts(payload, "next-stage")[1]
