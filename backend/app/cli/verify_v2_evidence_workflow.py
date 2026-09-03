"""No-network acceptance for constrained reasoning and case-draft governance."""

import json
from datetime import datetime, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.ai.diagnosis_graph import route_after_escalation, route_after_explanation
from app.ai.reasoning import _fallback_reasoning, _validate_reasoning
from app.db.base import Base
from app.knowledge.case_drafting import (
    CaseDraftError,
    apply_ai_assisted_polish,
    approve_case_draft,
    build_case_draft,
    submit_case_draft_for_review,
)
from app.knowledge.validation import validate_reasoning_against_knowledge
from app.models.diagnosis_feedback import DiagnosisFeedback
from app.models.diagnosis_result import DiagnosisResult
from app.models.guidance_history import GuidanceHistory


def _verify_reasoning_constraints() -> None:
    state = {
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
            }
        ],
    }
    allowed = [
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
    valid = _validate_reasoning(
        json.dumps(
            {
                "error_type": "SENSOR_READ_FAILED",
                "conclusion": "ranked",
                "ranked_causes": [
                    {
                        "cause_id": "gpio_config",
                        "cause": "不得改写",
                        "support_level": "high",
                        "used_evidence_ids": ["device:status", "rule:unknown:0"],
                        "reason": "设备在线且读取持续失败。",
                    }
                ],
                "summary": "现有证据更符合 GPIO 配置问题。",
                "limitations": [],
            },
            ensure_ascii=False,
        ),
        state,
        allowed,
    )
    if valid.ranked_causes[0].cause != "GPIO 配置错误":
        raise SystemExit("reasoning did not preserve the fault-tree cause")
    invalid = json.dumps(
        {
            "error_type": "SENSOR_READ_FAILED",
            "conclusion": "ranked",
            "ranked_causes": [
                {
                    "cause_id": "invented_damage",
                    "cause": "未知硬件损坏",
                    "support_level": "high",
                    "used_evidence_ids": [],
                    "reason": "猜测",
                }
            ],
            "summary": "越界结果",
            "limitations": [],
        },
        ensure_ascii=False,
    )
    try:
        _validate_reasoning(invalid, state, [])
    except ValueError:
        pass
    else:
        raise SystemExit("reasoning accepted a cause outside the fault tree")
    unknown = _fallback_reasoning(
        {"error_type": "SENSOR_READ_FAILED", "fault_tree_candidates": []},
        limitation="无候选原因",
    )
    if unknown.conclusion != "unknown":
        raise SystemExit("empty candidate set did not produce unknown")


def _verify_case_draft_governance() -> str:
    engine = create_engine("sqlite+pysqlite://")
    Base.metadata.create_all(engine)
    try:
        with Session(engine) as db:
            diagnosis = DiagnosisResult(
                device_id="case-draft-device",
                evaluated_at=datetime.now(timezone.utc),
                ruleset_version="v2-test",
                ruleset_hash="0" * 64,
                input_fingerprint="1" * 64,
                matched_rules=[
                    {
                        "rule_id": "sensor-read-failed",
                        "error_type": "SENSOR_READ_FAILED",
                        "summary": "DHT11 连续读取失败",
                        "evidence": [],
                    }
                ],
                evidence=[
                    {
                        "rule_id": "sensor-read-failed",
                        "items": [{"fact": "log_event_count", "observed_value": 20}],
                    }
                ],
                context_snapshot={
                    "experiment_template": {
                        "template_id": "dht11_temperature_humidity"
                    },
                    "readings": [],
                    "expected_behaviors": [],
                },
                experiment_id="dht11_temperature_humidity",
                deterministic_explanation={"steps": ["核对 GPIO 配置"]},
                is_test_data=True,
            )
            db.add(diagnosis)
            db.flush()
            feedback = DiagnosisFeedback(
                device_id="case-draft-device",
                diagnosis_result_id=diagnosis.id,
                action="resolved",
                note="核对 GPIO 后恢复",
                is_test_data=True,
            )
            db.add(feedback)
            db.flush()
            guidance = GuidanceHistory(
                device_id="case-draft-device",
                diagnosis_result_id=diagnosis.id,
                fault_tree_id="dht11-tree",
                fault_tree_title="DHT11",
                fault_tree_status="approved",
                fault_tree_version="1",
                fault_tree_hash="2" * 64,
                first_detected_at=diagnosis.evaluated_at,
                failure_count=2,
                anomaly_duration_seconds=30,
                hint_level=2,
                teacher_intervention_required=False,
                ranked_causes=[{"cause_id": "gpio_config", "title": "GPIO 配置错误"}],
                hints=[],
                is_test_data=True,
            )
            draft = build_case_draft(db, diagnosis, feedback, [guidance])
            if draft.status != "pending_review":
                raise SystemExit("verified case draft did not enter teacher review")
            if draft.root_cause.get("status") != "unknown":
                raise SystemExit("student feedback incorrectly confirmed a root cause")
            polished = dict(draft.template_payload)
            polished["symptom"] = "DHT11 连续读取失败，尚未获得有效数据。"
            polished["aiGeneratedFields"] = {
                "title": "DHT11 读取异常排查",
                "sourceIds": draft.source_ids,
            }
            apply_ai_assisted_polish(db, draft, polished)
            submit_case_draft_for_review(db, draft)
            changed = dict(polished)
            changed["possibleCauses"] = ["AI 创造的新故障"]
            try:
                apply_ai_assisted_polish(db, draft, changed)
            except CaseDraftError:
                pass
            else:
                raise SystemExit("AI polish changed verified case facts")
            case = approve_case_draft(
                db,
                draft,
                case_id="dht11.feedback-confirmed.v1",
                reviewer_ref="teacher-verification",
                confirmed_root_cause="GPIO 配置错误",
                final_solution_steps=["核对并修正 GPIO 配置", "重新运行并确认读数恢复"],
                confirmation_note="教师现场确认修改 GPIO 后连续读数恢复。",
            )
            if (
                case.review_status != "approved"
                or case.root_cause_status != "confirmed"
                or not case.facts_locked
                or not case.quality_check_passed
                or draft.reviewer_ref is None
            ):
                raise SystemExit("teacher approval did not publish the case")
            return case.id
    finally:
        Base.metadata.drop_all(engine)
        engine.dispose()


def main() -> None:
    _verify_reasoning_constraints()
    validation = validate_reasoning_against_knowledge(
        {
            "error_type": "SENSOR_READ_FAILED",
            "rule_hits": [{"error_type": "SENSOR_READ_FAILED"}],
            "fault_tree_candidates": [{"cause_id": "gpio_config"}],
            "reasoned_causes": [
                {
                    "cause_id": "gpio_config",
                    "support_level": "medium",
                    "used_evidence_ids": ["device:status"],
                }
            ],
            "evidence_registry": [{"id": "device:status"}],
            "allowed_verification_actions": [{"text": "核对 GPIO"}],
            "next_verification_action": "核对 GPIO",
            "knowledge_constraints": {"teacher_confirmed_cases": []},
        }
    )
    if validation["status"] != "validated_without_case":
        raise SystemExit("post-reasoning knowledge validation failed")
    if route_after_explanation({"error_type": "SENSOR_READ_FAILED"}) != "escalation_handler":
        raise SystemExit("initial anomaly does not enter escalation assessment")
    if (
        route_after_escalation(
            {"student_feedback": {"action": "unresolved"}, "needs_teacher": False}
        )
        != "knowledge_context"
    ):
        raise SystemExit("unresolved feedback does not continue diagnosis")
    case_id = _verify_case_draft_governance()
    print(
        {
            "reasoning_rejects_new_causes": True,
            "unknown_fallback": True,
            "unresolved_feedback_continues_reasoning": True,
            "knowledge_context_precedes_reasoning": True,
            "knowledge_validation_follows_reasoning": True,
            "ai_polish_preserves_facts": True,
            "student_feedback_does_not_confirm_root_cause": True,
            "formal_case_requires_teacher_confirmation": True,
            "teacher_approved_case_id": case_id,
            "rag_enabled": False,
        }
    )


if __name__ == "__main__":
    main()
