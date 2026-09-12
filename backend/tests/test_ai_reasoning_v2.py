import json

import pytest

from app.ai.diagnosis_graph import route_after_knowledge_validation
from app.ai.reasoning import _fallback_reasoning, _validate_reasoning
from app.ai.schemas import AIKnowledgeReference
from app.knowledge.validation import (
    build_reasoning_knowledge_constraints,
    validate_reasoning_against_knowledge,
)


def _state() -> dict:
    return {
        "device_status": {"status": "online"},
        "error_type": "SENSOR_READ_FAILED",
        "evidence": [{"fact": "log_event_count", "observed_value": 20}],
        "historical_failures": 2,
        "fault_tree_candidates": [
            {
                "cause_id": "gpio_config",
                "name": "GPIO 配置错误",
                "score": 0.8,
                "evidence_refs": ["00000000-0000-0000-0000-000000000001"],
            },
            {
                "cause_id": "wiring",
                "name": "接线问题",
                "score": 0.6,
                "evidence_refs": ["00000000-0000-0000-0000-000000000001"],
            },
        ],
    }


def test_reasoning_can_only_rank_known_causes_and_evidence() -> None:
    evidence = [
        {
            "id": "00000000-0000-0000-0000-000000000002",
            "fact": "设备状态=online",
            "source": "device",
        },
        {
            "id": "00000000-0000-0000-0000-000000000001",
            "fact": "规则证据:log_event_count=20",
            "source": "rule_engine",
        },
        {
            "id": "00000000-0000-0000-0000-000000000003",
            "fact": "历史失败次数=2",
            "source": "diagnosis_history",
        },
    ]
    result = _validate_reasoning(
        json.dumps(
            {
                "error_type": "SENSOR_READ_FAILED",
                "conclusion": "ranked",
                "ranked_causes": [
                    {
                        "cause_id": "gpio_config",
                        "cause": "模型不得改写这个原因",
                        "support_level": "high",
                        "used_evidence_ids": ["00000000-0000-0000-0000-000000000001"],
                        "reason": "合成规则事实：窗口累计读取失败。",
                    }
                ],
                "summary": "GPIO 配置错误更符合现有证据。",
                "limitations": [],
            },
            ensure_ascii=False,
        ),
        _state(),
        evidence,
    )

    assert result.ranked_causes[0].cause == "GPIO 配置错误"
    assert result.ranked_causes[0].support_level == "high"
    assert result.ranked_causes[0].used_evidence_ids == [
        "00000000-0000-0000-0000-000000000001",
    ]


def test_reasoning_rejects_new_faults() -> None:
    with pytest.raises(ValueError, match="unknown or duplicate cause"):
        _validate_reasoning(
            json.dumps(
                {
                    "error_type": "SENSOR_READ_FAILED",
                    "conclusion": "ranked",
                    "ranked_causes": [
                        {
                            "cause_id": "invented_damage",
                            "cause": "未经验证的硬件损坏",
                            "support_level": "high",
                            "used_evidence_ids": [],
                            "reason": "猜测。",
                        }
                    ],
                    "summary": "越界结果",
                    "limitations": [],
                },
                ensure_ascii=False,
            ),
            _state(),
            [],
        )


def test_reasoning_returns_unknown_without_candidates() -> None:
    result = _fallback_reasoning(
        {"error_type": "SENSOR_READ_FAILED", "fault_tree_candidates": []},
        limitation="没有候选原因",
    )

    assert result.conclusion == "unknown"
    assert result.ranked_causes == []


def test_pre_reasoning_knowledge_exposes_only_structured_constraints() -> None:
    reference = AIKnowledgeReference(
        chunk_id="dht11.case.v1",
        source_key="knowledge/cases/dht11.yaml",
        source_title="DHT11",
        source_type="structured_case",
        source_uri=None,
        content=json.dumps(
            {
                "caseId": "dht11.case.v1",
                "experimentType": "dht11_temperature_humidity",
                "errorType": "SENSOR_READ_FAILED",
                "symptom": "DHT11 连续读取失败",
                "normalState": {"metrics": ["temperature", "humidity"]},
                "possibleCauses": ["GPIO 配置错误"],
                "solutionSteps": ["核对 GPIO"],
                "teacherNotes": "以课程接线表为准",
                "rootCause": {"value": "GPIO 配置错误", "status": "confirmed"},
            },
            ensure_ascii=False,
        ),
        similarity=1.0,
        is_test_data=True,
    )

    constraints = build_reasoning_knowledge_constraints(
        {"experiment_id": "dht11_temperature_humidity"}, [reference]
    )

    assert constraints["experiment_definition"]["experiment_id"] == ("dht11_temperature_humidity")
    assert constraints["normal_conditions"][0]["normal_state"]["metrics"] == [
        "temperature",
        "humidity",
    ]
    assert constraints["teacher_confirmed_cases"][0]["case_id"] == "dht11.case.v1"


def test_post_reasoning_validation_rejects_unknown_cause_and_evidence() -> None:
    state = {
        "error_type": "SENSOR_READ_FAILED",
        "rule_hits": [{"error_type": "SENSOR_READ_FAILED"}],
        "fault_tree_candidates": [{"cause_id": "gpio_config"}],
        "reasoned_causes": [
            {
                "cause_id": "invented_damage",
                "support_level": "high",
                "used_evidence_ids": ["00000000-0000-0000-0000-000000000099"],
            }
        ],
        "evidence_registry": [{"id": "00000000-0000-0000-0000-000000000001"}],
        "allowed_verification_actions": [{"text": "核对 GPIO"}],
        "next_verification_action": "直接更换主板",
        "knowledge_constraints": {
            "teacher_confirmed_cases": [
                {"case_id": "dht11.case.v1", "error_type": "SENSOR_READ_FAILED"}
            ]
        },
    }

    result = validate_reasoning_against_knowledge(state)

    assert result["status"] == "rejected"
    assert result["checks"]["cause_ids_in_fault_tree"] is False
    assert result["checks"]["evidence_ids_exist"] is False
    assert result["checks"]["verification_action_allowed"] is False
    assert route_after_knowledge_validation({"knowledge_validation": result}) == ("teacher_review")
