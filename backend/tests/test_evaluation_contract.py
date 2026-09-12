"""Synthetic counterexamples for the first evaluation-governance phase."""

import json
from pathlib import Path

import pytest

from app.ai.reasoning import _fallback_reasoning, _validate_reasoning
from app.ai.schemas import AIDiagnosisInput
from app.evaluation import runner
from app.experiment_packages.loader import _run_package_tests, load_experiment_package
from app.knowledge.validation import validate_reasoning_against_knowledge
from app.services.ai_diagnosis import _validate_explanation


def reasoning_state():
    return {
        "error_type": "SENSOR_READ_FAILED",
        "fault_tree_candidates": [
            {"cause_id": "synthetic", "name": "合成候选", "score": 0.9, "evidence_refs": []}
        ],
        "allowed_verification_actions": [{"text": "保留日志并请求教师协助。"}],
    }


def reasoning_output(refs=()):
    return {
        "error_type": "SENSOR_READ_FAILED",
        "conclusion": "ranked",
        "ranked_causes": [
            {
                "cause_id": "synthetic",
                "cause": "合成候选",
                "support_level": "high",
                "used_evidence_ids": list(refs),
                "reason": "合成校验样例。",
            }
        ],
        "summary": "合成样例，不是硬件结论。",
    }


def explanation_input():
    return AIDiagnosisInput(
        diagnosis_result_id="synthetic",
        anonymous_device_id="synthetic",
        device_state={},
        logs=[],
        sensor_readings=[],
        heartbeats=[],
        knowledge=[],
        rule_matches=[{"error_type": "SENSOR_READ_FAILED"}],
        fault_tree_guidance=[],
        allowed_evidence=[],
        is_test_data=True,
        workflow_state={"allowed_verification_actions": [{"text": "保留日志并请求教师协助。"}]},
    )


def explanation_output():
    return {
        "error_type": "SENSOR_READ_FAILED",
        "summary": "合成样例。",
        "evidence": [],
        "possible_causes": [],
        "steps": ["保留日志并请求教师协助。"],
        "hint_level": 1,
        "need_teacher_help": False,
        "limitations": [],
    }


def test_high_support_without_evidence_is_rejected():
    with pytest.raises(ValueError, match="evidence"):
        _validate_reasoning(json.dumps(reasoning_output()), reasoning_state(), [])


def test_high_support_with_unknown_observation_is_rejected():
    evidence = [
        {"id": "synthetic-evidence", "fact": "level=1", "source": "reading", "status": "unknown"}
    ]
    with pytest.raises(ValueError, match="evidence"):
        _validate_reasoning(
            json.dumps(reasoning_output(["synthetic-evidence"])), reasoning_state(), evidence
        )


def test_high_support_with_allowed_observed_evidence_is_structurally_valid():
    evidence = [
        {"id": "synthetic-evidence", "fact": "test=1", "source": "rule", "status": "observed"}
    ]
    state = reasoning_state()
    state["fault_tree_candidates"][0]["evidence_refs"] = ["synthetic-evidence"]
    result = _validate_reasoning(
        json.dumps(reasoning_output(["synthetic-evidence"])), state, evidence
    )
    assert result.ranked_causes[0].support_level == "high"


def test_model_cannot_hide_input_conflict():
    state = {**reasoning_state(), "evidence_conflict": True}
    state["fault_tree_candidates"][0]["evidence_refs"] = ["e1"]
    with pytest.raises(ValueError, match="conflict"):
        _validate_reasoning(json.dumps(reasoning_output(["e1"])), state, [{"id": "e1"}])


def test_fallback_without_evidence_is_unknown_and_keeps_next_action():
    result = _fallback_reasoning(reasoning_state(), limitation="synthetic")
    assert result.conclusion == "unknown"
    assert result.ranked_causes == []
    assert result.next_verification_action == "保留日志并请求教师协助。"


def test_fallback_does_not_borrow_unrelated_evidence_for_a_cause():
    state = {
        **reasoning_state(),
        "evidence_registry": [{"id": "other", "fact": "test=1", "source": "rule"}],
    }
    result = _fallback_reasoning(state, limitation="synthetic")
    assert result.conclusion == "unknown"
    assert result.ranked_causes == []


def test_explanation_rejects_unlisted_step():
    output = {**explanation_output(), "steps": ["直接更换主板。"]}
    with pytest.raises(ValueError, match="step"):
        _validate_explanation(json.dumps(output), explanation_input())


def test_explanation_accepts_exact_allowed_step():
    result = _validate_explanation(json.dumps(explanation_output()), explanation_input())
    assert result.steps == ["保留日志并请求教师协助。"]


def test_empty_workflow_actions_do_not_fall_back_to_other_hints():
    payload = explanation_input()
    payload.workflow_state["allowed_verification_actions"] = []
    payload.fault_tree_guidance = [{"hints": [{"text": "保留日志并请求教师协助。"}]}]
    with pytest.raises(ValueError, match="step"):
        _validate_explanation(json.dumps(explanation_output()), payload)


@pytest.mark.parametrize(
    "claim",
    [
        "已确认根因是传感器损坏。",
        "只要 level=1，LED 就已经亮了。",
        "窗口累计失败五次就是连续失败五次。",
    ],
)
def test_model_prose_cannot_replace_server_owned_fact_summary(claim):
    output = {**explanation_output(), "summary": claim, "limitations": [claim]}
    result = _validate_explanation(json.dumps(output), explanation_input())
    assert claim not in result.summary
    assert claim not in result.limitations
    assert "候选" in result.summary or "根因" in result.summary


@pytest.mark.parametrize("field", ["summary", "steps", "limitations"])
def test_forbidden_claim_gate_reads_rendered_explanation(monkeypatch, field):
    original = runner.render_deterministic_explanation

    def mutated(core):
        output = original(core)
        value = "真实硬件验证通过" if field == "summary" else ["真实硬件验证通过"]
        return output.model_copy(update={field: value})

    monkeypatch.setattr(runner, "render_deterministic_explanation", mutated)
    report = runner.run_evaluation()
    assert report["forbidden_claims"]["hits"]
    assert report["passed"] is False


def test_package_fault_sample_rejects_an_additional_error_type():
    bundle, _ = load_experiment_package(
        Path(__file__).resolve().parents[1] / "experiment_packages/dht11_temperature_humidity"
    )
    assert all(check.passed for check in _run_package_tests(bundle))
    # Same trigger, additional error: a contains-only expectation missed this.
    duplicate = bundle.rules.rules[0].model_copy(update={"error_type": "SYNTHETIC_EXTRA"})
    bundle.rules.rules.append(duplicate)
    faults = [check for check in _run_package_tests(bundle) if check.code.startswith("test.fault.")]
    assert faults and all(not check.passed for check in faults)


def test_post_reasoning_guard_independently_rejects_high_without_evidence():
    state = reasoning_state()
    state["reasoned_causes"] = reasoning_output()["ranked_causes"]
    result = validate_reasoning_against_knowledge(state)
    assert result["checks"]["high_support_has_evidence"] is False
    assert result["status"] == "rejected"
