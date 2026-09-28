import hashlib
import json
from copy import deepcopy
from datetime import datetime, timezone
from uuid import uuid4

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from pydantic import ValidationError

from app.ai.clients import AICompletion
from app.ai.context_sanitizer import build_safe_ai_input, sanitize_provider_payload
from app.ai.diagnosis_graph import build_diagnosis_graph
from app.ai.reasoning import _fallback_reasoning, _reasoning_prompt, reason_about_causes
from app.core.config import Settings
from app.diagnosis.workflow_schemas import DiagnosisWorkflowStartRequest
from app.models import AICallRecord, Device, DiagnosisResult
from app.services.ai_diagnosis import explain_diagnosis
from app.services.diagnosis_workflow import start_workflow


class EvidenceReviewProvider:
    """Scripted output tests transport/guards, not model reasoning quality."""

    configured = True
    provider = "synthetic"
    model = "synthetic-evidence-review"

    def __init__(self, *, invalid_action=False):
        self.requests = []
        self.invalid_action = invalid_action

    def complete_json(self, *, system_prompt, user_prompt):
        self.requests.append((system_prompt, user_prompt))
        return AICompletion(json.dumps({
            "error_type": "SENSOR_READ_FAILED",
            "conclusion": "unknown",
            "ranked_causes": [],
            "summary": "当前合成材料不足以区分候选原因。",
            "limitations": ["尚未确认实际接线。"],
            "missing_evidence": ["需要核对实际接线与程序引脚。"],
            "next_verification_action": "执行白名单外操作" if self.invalid_action else None,
            "conflict": False,
        }, ensure_ascii=False), input_tokens=10, output_tokens=10)


@pytest.fixture
def evidence_review_run(api_context, request):
    _post_failure(api_context)
    provider = EvidenceReviewProvider(invalid_action=getattr(request, "param", False))
    graph = build_diagnosis_graph(InMemorySaver())
    with api_context["session_factory"]() as db:
        workflow = start_workflow(
            db, graph, db.query(Device).one(),
            Settings(_env_file=None, ai_enabled=False, diagnosis_teacher_review_score=0),
            DiagnosisWorkflowStartRequest(lookback_seconds=60),
        )
        state = dict(graph.get_state({"configurable": {
            "thread_id": workflow.graph_thread_id,
        }}).values)
        diagnosis = db.get(DiagnosisResult, state["diagnosis_result_id"])
        settings = Settings(_env_file=None, ai_enabled=True, ai_require_knowledge=False,
                            ai_max_retries=0, ai_input_token_limit=20000)

        def run():
            return reason_about_causes(
                db, diagnosis, state, settings, workflow_run_id=workflow.id,
                call_stage="reasoning:cot-contract-test", ai_client=provider,
            )

        result, mode = run()
        record = db.query(AICallRecord).filter_by(
            call_stage="reasoning:cot-contract-test",
        ).one()
        yield provider, result, mode, record, run, db


def test_evidence_review_uses_one_governed_call(evidence_review_run):
    provider, result, mode, record, _, _ = evidence_review_run
    assert len(provider.requests) == record.attempt_count == 1
    assert mode == "ai"
    assert result.conclusion == "unknown"
    assert result.ranked_causes == []
    assert record.output_json == result.model_dump(mode="json")


def test_evidence_review_request_and_audit_keep_versioned_contract(evidence_review_run):
    provider, _, _, record, _, _ = evidence_review_run
    system, user = provider.requests[0]
    document = json.loads(user)
    assert document["prompt_version"] == record.prompt_version == "evidence-reasoning-v2.7"
    assert record.prompt_hash == hashlib.sha256(f"{system}\n{user}".encode()).hexdigest()
    assert set(document) == {
        "prompt_version", "error_type", "device_status", "experiment_context",
        "candidate_causes", "evidence_registry", "knowledge_constraints",
        "allowed_verification_actions", "output_json_schema",
    }
    assert document["error_type"] == "SENSOR_READ_FAILED"
    assert "cot_steps" not in document["output_json_schema"]["properties"]


@pytest.mark.parametrize("evidence_review_run", [True], indirect=True)
def test_evidence_review_cannot_bypass_action_assertions(evidence_review_run):
    provider, result, mode, record, _, _ = evidence_review_run
    assert mode == "deterministic_fallback"
    assert record.validation_status == "fallback"
    assert record.fallback_reason == "ValueError"
    assert result.next_verification_action != "执行白名单外操作"
    assert len(provider.requests) == 1


def test_old_reasoning_replay_is_not_relabelled_or_called_again(evidence_review_run):
    provider, result, _, record, run, db = evidence_review_run
    record.prompt_version = "evidence-reasoning-v2.5"
    record.prompt_hash = "historical-synthetic-hash"
    record.input_snapshot = {key: value for key, value in record.input_snapshot.items()
                             if key != "context_manifest"}
    db.commit()
    replay, mode = run()
    assert replay == result
    assert mode == "ai"
    assert len(provider.requests) == 1
    db.refresh(record)
    assert record.prompt_version == "evidence-reasoning-v2.5"
    assert record.prompt_hash == "historical-synthetic-hash"
    assert "context_manifest" not in record.input_snapshot


def _state(count=35, candidates=1):
    refs = [str(uuid4()) for _ in range(count)]
    return {
        "error_type": "SENSOR_READ_FAILED", "evidence_conflict": True,
        "evidence_registry": [
            {"id": ref, "fact": "合成失败", "source": "rule_engine", "status": "observed"}
            for ref in refs
        ],
        "fault_tree_candidates": [
            {"cause_id": f"cause-{i:02}", "name": "候选", "score": .9,
             "evidence_refs": [*reversed(refs), *refs[:2]]}
            for i in range(candidates)
        ],
    }


@pytest.mark.parametrize("count", [0, 30, 31, 35, 50])
def test_fallback_bounds_real_references_and_preserves_conflict(count):
    state = _state(count)
    original = deepcopy(state)
    result = _fallback_reasoning(state, limitation="测试降级")
    assert state == original
    assert result.conflict is True
    if count:
        cause = result.ranked_causes[0]
        assert cause.used_evidence_ids == [item["id"] for item in state["evidence_registry"][:30]]
        assert cause.support_level != "high"
    else:
        assert result.conclusion == "unknown"
        assert result.ranked_causes == []


def test_fallback_bounds_candidates_without_mutating_full_space():
    state = _state(1, candidates=25)
    result = _fallback_reasoning(state, limitation="测试降级")
    assert len(result.ranked_causes) == 20
    assert len(state["fault_tree_candidates"]) == 25
    assert result.ranked_causes[-1].cause_id == "cause-19"
    assert any("部分" in item for item in result.limitations)


def _post_failure(ctx, *, count=1, private=False):
    for _ in range(count):
        result = ctx["client"].post("/api/v1/device/logs", headers=ctx["headers"], json={
            "level": "error", "event_code": "SENSOR_READ_FAILED",
            "message": "李明反馈读取失败" if private else "合成失败",
            "sensor_snapshot": {"student_name": "李明"} if private else {},
            "occurred_at": datetime.now(timezone.utc).isoformat(), "is_test_data": True,
        })
        assert result.status_code == 201


def _post_reading(ctx, unit):
    result = ctx["client"].post("/api/v1/device/readings", headers=ctx["headers"], json={
        "sensor_type": "dht11", "metric_key": "temperature", "value": 25,
        "unit": unit, "observed_at": datetime.now(timezone.utc).isoformat(),
        "is_test_data": True,
    })
    assert result.status_code == 201


def _diagnosis(ctx, db):
    response = ctx["client"].post(
        "/api/v1/diagnosis/devices/phase2-test-device/run", headers=ctx["headers"],
        json={"lookback_seconds": 60},
    )
    assert response.status_code == 201
    return db.get(DiagnosisResult, response.json()["id"])


@pytest.mark.parametrize("scenario", ["many-evidence", "mixed-units"])
def test_full_workflow_remains_usable_without_ai(api_context, scenario):
    _post_failure(api_context, count=35 if scenario == "many-evidence" else 1)
    if scenario == "mixed-units":
        _post_reading(api_context, None)
        _post_reading(api_context, "C")
    with api_context["session_factory"]() as db:
        graph = build_diagnosis_graph(InMemorySaver())
        result = start_workflow(
            db, graph, db.query(Device).one(),
            Settings(_env_file=None, ai_enabled=False, diagnosis_teacher_review_score=0),
            DiagnosisWorkflowStartRequest(lookback_seconds=60),
        )
        assert result.status in {"waiting_feedback", "waiting_teacher"}
        state = graph.get_state({"configurable": {
            "thread_id": result.graph_thread_id,
        }}).values
        assert "ai_explanation" in state["node_trace"]
        assert state["error_type"] == "SENSOR_READ_FAILED"
        assert state["reasoning_status"] == "fallback"


def test_units_are_separate_and_projection_removes_short_secrets():
    context = {
        "device_id": "test-device", "student_name": "李明",
        "logs": [{"level": "error", "message": "李明说失败", "event_code": "error"}],
        "readings": [{"sensor_type": "dht11", "metric_key": "temperature", "value": 25,
                      "unit": unit} for unit in (None, "", "C")],
    }
    record = DiagnosisResult(id=str(uuid4()), matched_rules=[], context_snapshot=context,
                             is_test_data=True)
    payload = build_safe_ai_input(record, [], [], Settings(_env_file=None),
                                 episode_id=None, user_question=None)
    assert "李明" not in payload.model_dump_json()
    assert {item["unit"] for item in payload.sensor_readings} == {None, "", "C"}
    assert all(item["sample_count"] == 1 for item in payload.sensor_readings)
    assert all(item["latest"] == 25 for item in payload.sensor_readings)


def test_only_verified_path_and_value_can_preserve_a_reference():
    ref = str(uuid4())
    payload = {"sources": [ref], "knowledge": {"normalState": {
        "api_key": "synthetic-secret", "reference": {"id": "synthetic-secret"},
        "owner": {"id": "student@example.com"},
    }}}
    original = deepcopy(payload)
    safe = sanitize_provider_payload(
        payload, allowed_fields=("sources", "knowledge"),
        trusted_references={("sources", "*"): {ref}},
    )
    assert safe["sources"] == [ref]
    assert "synthetic-secret" not in json.dumps(safe)
    assert "student@example.com" not in json.dumps(safe)
    assert payload == original
    with pytest.raises(ValueError):
        sanitize_provider_payload(payload, allowed_fields=("sources",),
                                  trusted_references={("sources", "*"): {"other"}})
    with pytest.raises(ValueError):
        sanitize_provider_payload(
            {"sources": [ref]}, allowed_fields=("sources",),
            trusted_references={("sources", "*"): {ref}},
            sensitive_sources=({"api_key": ref},),
        )


class CaptureProvider:
    configured = True
    provider = "synthetic"
    model = "synthetic"

    def __init__(self):
        self.prompts = []

    def complete_json(self, *, system_prompt, user_prompt):
        self.prompts.append(user_prompt)
        return AICompletion("{}", input_tokens=1, output_tokens=1)


def test_real_explanation_provider_receives_no_private_labels(api_context):
    _post_failure(api_context, private=True)
    _post_reading(api_context, "password=synthetic-unit-secret")
    provider = CaptureProvider()
    with api_context["session_factory"]() as db:
        diagnosis = _diagnosis(api_context, db)
        explain_diagnosis(
            db, db.query(Device).one(), diagnosis,
            Settings(_env_file=None, ai_enabled=True, ai_require_knowledge=False,
                     ai_max_retries=0, ai_input_token_limit=10000),
            ai_client=provider, user_question="请解释异常",
        )
    assert len(provider.prompts) == 1
    assert "李明" not in provider.prompts[0]
    assert "synthetic-unit-secret" not in provider.prompts[0]


def test_reasoning_projection_uses_original_secrets_and_nested_ids():
    state = _state(1)
    state["knowledge_constraints"] = {"normal_conditions": [{"normal_state": {
        "api_key": "synthetic-secret", "reference": {"id": "synthetic-secret"},
        "description": "李明报告异常",
    }}]}
    _, prompt, _, _ = _reasoning_prompt(
        state, sensitive_sources=({"student_name": "李明"},),
    )
    assert "synthetic-secret" not in prompt
    assert "李明" not in prompt
    assert state["evidence_registry"][0]["id"] in prompt


@pytest.mark.parametrize("enabled", [False, True])
def test_explanation_projection_failure_never_breaks_deterministic_result(
    api_context, monkeypatch, enabled,
):
    _post_failure(api_context)
    provider = CaptureProvider()

    def broken(*args, **kwargs):
        raise ValueError("synthetic projection failure")

    monkeypatch.setattr("app.services.ai_diagnosis._build_input", broken)
    with api_context["session_factory"]() as db:
        result = explain_diagnosis(
            db, db.query(Device).one(), _diagnosis(api_context, db),
            Settings(_env_file=None, ai_enabled=enabled, ai_require_knowledge=False),
            ai_client=provider, user_question="请解释异常",
        )
        assert result.mode == "rules_only"
        assert result.deterministic_result is not None
        assert db.get(AICallRecord, result.call_record_id).attempt_count == 0
    assert provider.prompts == []


@pytest.mark.parametrize("field", ["ai_daily_budget", "ai_max_cost_per_call",
                                  "ai_input_cost_per_1k_tokens", "ai_output_cost_per_1k_tokens"])
@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf"), "NaN", "Inf", "-Inf"])
def test_cost_configuration_rejects_nonfinite_values(field, value):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, **{field: value})


@pytest.mark.parametrize("collision", [False, True])
def test_real_reasoning_provider_boundary(api_context, collision):
    _post_failure(api_context, private=True)
    provider = CaptureProvider()
    graph = build_diagnosis_graph(InMemorySaver())
    with api_context["session_factory"]() as db:
        workflow = start_workflow(
            db, graph, db.query(Device).one(),
            Settings(_env_file=None, ai_enabled=False, diagnosis_teacher_review_score=0),
            DiagnosisWorkflowStartRequest(lookback_seconds=60),
        )
        state = dict(graph.get_state({"configurable": {
            "thread_id": workflow.graph_thread_id,
        }}).values)
        diagnosis = db.get(DiagnosisResult, state["diagnosis_result_id"])
        if collision:
            diagnosis.context_snapshot = {**diagnosis.context_snapshot,
                "api_key": state["evidence_registry"][0]["id"]}
            db.commit()
        state["knowledge_constraints"] = {"normal_conditions": [{"normal_state": {
            "api_key": "synthetic-secret", "reference": {"id": "synthetic-secret"},
            "description": "李明报告异常",
        }}]}
        result, mode = reason_about_causes(
            db, diagnosis, state,
            Settings(_env_file=None, ai_enabled=True, ai_require_knowledge=False,
                     ai_max_retries=0, ai_input_token_limit=20000),
            workflow_run_id=workflow.id, call_stage="reasoning:privacy-test",
            ai_client=provider,
        )
        assert mode == "deterministic_fallback"
        assert result.error_type == state["error_type"]
        record = db.query(AICallRecord).filter_by(call_stage="reasoning:privacy-test").one()
        if collision:
            assert provider.prompts == []
            assert record.attempt_count == 0
            assert record.fallback_reason == "AI_INPUT_UNSAFE_REFERENCE"
        else:
            assert len(provider.prompts) == 1
            assert "李明" not in provider.prompts[0]
            assert "synthetic-secret" not in provider.prompts[0]
            assert state["evidence_registry"][0]["id"] in provider.prompts[0]
