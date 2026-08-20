"""Create explicitly marked runtime artifacts for the Phase 9 final acceptance."""

from __future__ import annotations

import json
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select

from app.ai.clients import AICompletion
from app.cli.seed_phase9_test_knowledge import (
    TEST_VECTOR_MODEL,
    TEST_VECTOR_PROVIDER,
)
from app.core.config import Settings
from app.core.security import hash_device_token
from app.db.session import SessionLocal
from app.models.ai_call_record import AICallRecord
from app.models.ai_explanation_cache import AIExplanationCache
from app.models.device import Device
from app.models.diagnosis_result import DiagnosisResult
from app.schemas.device import DeviceHeartbeatCreate, DeviceLogCreate
from app.services.ai_diagnosis import explain_diagnosis
from app.services.device_ingest import save_heartbeat, save_log
from app.services.diagnosis import build_diagnosis_context, diagnose, save_diagnosis_result
from app.services.diagnosis_episode import resolve_episode, upsert_episode
from app.services.guidance import generate_guidance
from app.services.lightweight_diagnosis import (
    build_diagnosis_core,
    render_deterministic_explanation,
)

DEVICE_KEY = "phase9-runtime-acceptance"
QUESTION = "请基于当前确定性证据解释为什么连续读取失败。"


class TestFixtureEmbeddingClient:
    provider = TEST_VECTOR_PROVIDER
    model = TEST_VECTOR_MODEL
    dimensions = 4
    configured = True

    def embed(self, text: str) -> list[float]:
        del text
        return [1.0, 0.0, 0.0, 0.0]


class RuntimeMockAI:
    provider = "phase9-runtime-mock"
    model = "structured-fixture-v1"
    configured = True

    def __init__(self, explanation: dict[str, Any]) -> None:
        self.explanation = explanation
        self.calls = 0

    def complete_json(self, *, system_prompt: str, user_prompt: str) -> AICompletion:
        assert "不得覆盖" in system_prompt
        assert "allowed_evidence" in user_prompt
        self.calls += 1
        return AICompletion(
            content=json.dumps(self.explanation, ensure_ascii=False),
            input_tokens=120,
            output_tokens=80,
        )


def _device(db: Any) -> Device:
    device = db.scalar(select(Device).where(Device.device_key == DEVICE_KEY))
    if device is None:
        device = Device(
            device_key=DEVICE_KEY,
            display_name="Phase 9 明确标记的运行验收设备",
            device_type="generic-test-fixture",
            token_hash=hash_device_token(secrets.token_urlsafe(32)),
            metadata_json={"fixture": "phase9-runtime-acceptance"},
        )
        db.add(device)
        db.commit()
        db.refresh(device)
    return device


def _valid_explanation(diagnosis: DiagnosisResult) -> dict[str, Any]:
    match = diagnosis.matched_rules[0]
    evidence = match["evidence"][0]
    return {
        "error_type": match["error_type"],
        "summary": "Mock Provider 仅补充解释，确定性规则结果保持不变。",
        "evidence": [f"{evidence['fact']}: {evidence['observed_value']}"],
        "possible_causes": [],
        "steps": ["继续执行已生成的确定性分层排查步骤。"],
        "hint_level": 2,
        "need_teacher_help": False,
        "limitations": ["合成测试知识和 Mock Provider 不能证明真实硬件诊断能力。"],
    }


def main() -> None:
    now = datetime.now(timezone.utc)
    settings = Settings(
        ai_enabled=True,
        ai_transport="openai-compatible",
        ai_provider="phase9-runtime-mock",
        ai_base_url="https://invalid.example/v1",
        ai_model="structured-fixture-v1",
        ai_api_key="test-only-not-a-real-key",
        ai_require_knowledge=True,
        ai_max_retries=0,
        ai_calls_per_episode=2,
        ai_calls_per_device_hour=4,
        ai_input_cost_per_1k_tokens=0.001,
        ai_output_cost_per_1k_tokens=0.002,
    )
    with SessionLocal() as db:
        device = _device(db)
        save_heartbeat(
            db,
            device,
            DeviceHeartbeatCreate(
                observed_at=now,
                metadata={"fixture": "phase9-runtime-acceptance"},
                is_test_data=True,
            ),
        )
        episode = None
        diagnosis_record = None
        for index in range(5):
            save_log(
                db,
                device,
                DeviceLogCreate(
                    level="error",
                    message="Phase 9 合成运行验收：连续传感器读取失败",
                    event_code="SENSOR_READ_FAILED",
                    occurred_at=now - timedelta(seconds=4 - index),
                    sensor_snapshot={"fixture": "phase9-runtime-acceptance"},
                    is_test_data=True,
                ),
            )
            context = build_diagnosis_context(
                db,
                device,
                evaluated_at=now + timedelta(milliseconds=index),
                lookback_seconds=60,
            )
            outcome = diagnose(context)
            diagnosis_record = save_diagnosis_result(db, device, context, outcome)
            guidance = generate_guidance(db, device, diagnosis_record)
            core = build_diagnosis_core(diagnosis_record, guidance)
            deterministic = render_deterministic_explanation(core)
            diagnosis_record.deterministic_core = core.model_dump(mode="json")
            diagnosis_record.deterministic_explanation = deterministic.model_dump(mode="json")
            diagnosis_record.ai_enhancement = {
                "status": "skipped",
                "trigger_reason": "NOT_REQUESTED",
                "route": "none",
                "cache_status": "not_checked",
            }
            episode = upsert_episode(db, device, diagnosis_record, guidance, settings)
            db.commit()
        if diagnosis_record is None or episode is None:
            raise RuntimeError("Phase 9 runtime diagnosis was not created")

        mock = RuntimeMockAI(_valid_explanation(diagnosis_record))
        first = explain_diagnosis(
            db,
            device,
            diagnosis_record,
            settings,
            ai_clients=[("local", mock)],
            embedding_client=TestFixtureEmbeddingClient(),
            user_question=QUESTION,
        )
        second = explain_diagnosis(
            db,
            device,
            diagnosis_record,
            settings,
            ai_clients=[("local", mock)],
            embedding_client=TestFixtureEmbeddingClient(),
            user_question=QUESTION,
        )
        resolve_episode(db, episode, "phase9_runtime_acceptance")
        calls = db.scalars(
            select(AICallRecord)
            .where(AICallRecord.diagnosis_result_id == diagnosis_record.id)
            .order_by(AICallRecord.created_at)
        ).all()
        cache = db.scalar(
            select(AIExplanationCache).where(AIExplanationCache.fingerprint.is_not(None))
        )
        print(
            json.dumps(
                {
                    "device_key": device.device_key,
                    "diagnosis_id": diagnosis_record.id,
                    "episode_id": episode.id,
                    "episode_status": episode.status,
                    "failure_count": episode.failure_count,
                    "provider_calls": mock.calls,
                    "first_status": first.enhancement_status,
                    "second_status": second.enhancement_status,
                    "audit": [
                        {
                            "status": item.status,
                            "attempt_count": item.attempt_count,
                            "cache_status": item.cache_status,
                            "route": item.route,
                            "trigger_reason": item.trigger_reason,
                            "validation_status": item.validation_status,
                            "estimated_cost": item.estimated_cost,
                        }
                        for item in calls
                    ],
                    "cache_hit_count": cache.hit_count if cache else None,
                },
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
        )


if __name__ == "__main__":
    main()
