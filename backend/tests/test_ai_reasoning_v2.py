import json

import pytest

from app.ai.reasoning import _fallback_reasoning, _validate_reasoning


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
                "evidence_refs": ["log:1"],
            },
            {
                "cause_id": "wiring",
                "name": "接线问题",
                "score": 0.6,
                "evidence_refs": ["log:1"],
            },
        ],
    }


def test_reasoning_can_only_rank_known_causes_and_evidence() -> None:
    evidence = [
        {"id": "device:status", "fact": "设备状态=online", "source": "device"},
        {
            "id": "rule:unknown:0",
            "fact": "规则证据:log_event_count=20",
            "source": "rule_engine",
        },
        {
            "id": "history:failure_count",
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
                        "used_evidence_ids": ["device:status", "rule:unknown:0"],
                        "reason": "设备在线且连续读取失败。",
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
        "device:status",
        "rule:unknown:0",
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
