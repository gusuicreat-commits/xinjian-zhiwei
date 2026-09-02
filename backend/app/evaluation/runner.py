import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from time import perf_counter
from typing import Any

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.config import Settings
from app.db.base import Base
from app.diagnosis.schemas import (
    ContextLog,
    ContextReading,
    DiagnosisContext,
    ExperimentTemplateContext,
    MetricRange,
)
from app.models import Device, DiagnosisEpisode, DiagnosisResult
from app.services.diagnosis import diagnose
from app.services.diagnosis_episode import upsert_episode
from app.services.lightweight_diagnosis import build_diagnosis_core

EVALUATION_DIRECTORY = Path(__file__).resolve().parents[2] / "evaluation"


def _load(name: str) -> dict[str, Any]:
    return json.loads((EVALUATION_DIRECTORY / name).read_text(encoding="utf-8"))


def _diagnose_case(case: dict[str, Any]) -> dict[str, Any]:
    evaluated_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
    logs = []
    if case["event"] is not None:
        logs.append(
            ContextLog(
                id=f"log-{case['id']}",
                level="error",
                message="synthetic evaluation event",
                event_code=case["event"],
                occurred_at=evaluated_at,
                is_test_data=True,
            )
        )
    context = DiagnosisContext(
        device_id=f"synthetic-{case['id']}",
        evaluated_at=evaluated_at,
        last_seen_at=evaluated_at - timedelta(seconds=case["seconds_since_seen"]),
        logs=logs,
        readings=[
            ContextReading(
                id=f"reading-{case['id']}",
                sensor_type="synthetic-sensor",
                metric_key="synthetic_metric",
                value=case["value"],
                unit="synthetic-unit",
                observed_at=evaluated_at,
                is_test_data=True,
            )
        ],
        experiment_template=ExperimentTemplateContext(
            template_id="synthetic-template",
            metric_ranges={"synthetic_metric": MetricRange(minimum=0, maximum=100)},
        ),
    )
    started = perf_counter()
    outcome = diagnose(context)
    latency_ms = (perf_counter() - started) * 1000
    record = DiagnosisResult(
        id=f"diagnosis-{case['id']}",
        device_id=f"device-{case['id']}",
        evaluated_at=evaluated_at,
        ruleset_version=outcome.ruleset_version,
        ruleset_hash=outcome.ruleset_hash,
        input_fingerprint=outcome.input_fingerprint,
        matched_rules=[item.model_dump(mode="json") for item in outcome.matches],
        evidence=[
            {
                "rule_id": item.rule_id,
                "items": [evidence.model_dump(mode="json") for evidence in item.evidence],
            }
            for item in outcome.matches
        ],
        context_snapshot=context.model_dump(mode="json"),
        is_test_data=True,
    )
    return {
        "actual": [match.error_type for match in outcome.matches],
        "core": build_diagnosis_core(record, []),
        "latency_ms": latency_ms,
    }


def _evaluate_episode_aggregation() -> dict[str, Any]:
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    try:
        with session_factory() as db:
            device = Device(
                device_key="synthetic-evaluation-device",
                display_name="Synthetic evaluation device",
                device_type="test-fixture",
                token_hash="synthetic-hash-not-a-credential",
            )
            db.add(device)
            db.flush()
            for index in range(2):
                evaluated_at = datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(
                    seconds=index
                )
                diagnosis = DiagnosisResult(
                    device_id=device.id,
                    evaluated_at=evaluated_at,
                    ruleset_version="synthetic-evaluation",
                    ruleset_hash="0" * 64,
                    input_fingerprint=f"{index:064d}",
                    matched_rules=[
                        {
                            "rule_id": "synthetic-read-failure",
                            "error_type": "SENSOR_READ_FAILED",
                            "summary": "synthetic",
                            "evidence": [{"fact": "synthetic", "observed_value": 1}],
                        }
                    ],
                    evidence=[{"fact": "synthetic", "observed_value": 1}],
                    context_snapshot={"experiment_template": {"template_id": "synthetic"}},
                    is_test_data=True,
                )
                db.add(diagnosis)
                db.commit()
                upsert_episode(db, device, diagnosis, [], Settings(_env_file=None))
            episodes = list(db.scalars(select(DiagnosisEpisode)))
            passed = (
                len(episodes) == 1
                and episodes[0].failure_count == 2
                and episodes[0].primary_error_code == "SENSOR_READ_FAILED"
            )
            return {
                "input_diagnoses": 2,
                "episode_count": len(episodes),
                "failure_count": episodes[0].failure_count if episodes else 0,
                "passed": passed,
            }
    finally:
        Base.metadata.drop_all(engine)
        engine.dispose()


def run_evaluation() -> dict[str, Any]:
    diagnosis = _load("golden_cases.json")
    forbidden = _load("forbidden_claims.json")
    diagnosis_results = []
    latencies = []
    top1_cause_hits = 0
    top3_cause_hits = 0
    cause_cases = 0
    step_cases = 0
    step_passed = 0
    unsupported_high_confidence = 0
    for case in diagnosis["cases"]:
        evaluated = _diagnose_case(case)
        actual = evaluated["actual"]
        core = evaluated["core"]
        latencies.append(evaluated["latency_ms"])
        if core.confidence >= 0.7 and not core.evidence:
            unsupported_high_confidence += 1
        primary = case["expected"][0] if case["expected"] else None
        if primary:
            cause_cases += 1
            expected_cause = diagnosis["expected_causes_by_error"][primary]
            top1_cause_hits += bool(
                core.possible_causes and core.possible_causes[0] == expected_cause
            )
            top3_cause_hits += expected_cause in core.possible_causes[:3]
            step_cases += 1
            rendered_steps = " ".join(core.suggested_steps)
            required = diagnosis["required_step_fragments_by_error"][primary]
            step_passed += all(fragment in rendered_steps for fragment in required)
        diagnosis_results.append(
            {
                "id": case["id"],
                "expected": case["expected"],
                "actual": actual,
                "passed": actual == case["expected"],
            }
        )

    generated_text = " ".join(match for result in diagnosis_results for match in result["actual"])
    forbidden_hits = [pattern for pattern in forbidden["patterns"] if pattern in generated_text]
    diagnosis_passed = sum(item["passed"] for item in diagnosis_results)
    episode = _evaluate_episode_aggregation()
    cause_top1_rate = top1_cause_hits / cause_cases
    cause_top3_rate = top3_cause_hits / cause_cases
    required_steps_rate = step_passed / step_cases
    passed = (
        diagnosis_passed == len(diagnosis_results)
        and cause_top1_rate == 1.0
        and cause_top3_rate == 1.0
        and required_steps_rate == 1.0
        and unsupported_high_confidence == 0
        and not forbidden_hits
        and episode["passed"]
    )
    return {
        "evaluation_version": "5-v2-state-workflow",
        "is_test_data": True,
        "claim_boundary": "合成评测只验证确定性规则、解释与 Episode，不代表真实硬件能力。",
        "diagnosis": {
            "total": len(diagnosis_results),
            "passed": diagnosis_passed,
            "exact_match_rate": diagnosis_passed / len(diagnosis_results),
            "top1_cause_hit_rate": cause_top1_rate,
            "top3_cause_hit_rate": cause_top3_rate,
            "required_steps_rate": required_steps_rate,
            "unsupported_high_confidence_count": unsupported_high_confidence,
            "average_response_ms": sum(latencies) / len(latencies),
            "threshold": 1.0,
            "cases": diagnosis_results,
        },
        "knowledge_matching": {
            "mode": "structured_case_match",
            "rag_enabled": False,
            "note": "结构化案例匹配由独立测试覆盖，不计算向量召回指标。",
        },
        "forbidden_claims": {
            "patterns_checked": len(forbidden["patterns"]),
            "hits": forbidden_hits,
            "passed": not forbidden_hits,
        },
        "episode_aggregation": episode,
        "ai_activity": {
            "provider_calls": 0,
            "cache_hits": 0,
            "passed": True,
            "reason": "合成评测不调用 AI",
        },
        "passed": passed,
    }
