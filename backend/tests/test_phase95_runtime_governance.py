from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

import pytest
from pydantic import ValidationError

from app.ai.clients import (
    AICompletion,
    AIProviderError,
    DisabledEmbeddingClient,
    OpenAICompatibleClient,
    build_ai_client,
)
from app.ai.context_sanitizer import audit_snapshot, build_safe_ai_input
from app.ai.schemas import AIKnowledgeReference
from app.core.config import Settings
from app.models import AICallRecord, Device, DiagnosisResult, KnowledgeDocument
from app.schemas.knowledge import (
    KnowledgeReviewRequest,
    KnowledgeSourceCreate,
    KnowledgeTextImportRequest,
)
from app.services.ai_diagnosis import explain_diagnosis, get_ai_status
from app.services.hybrid_retrieval import hybrid_retrieve
from app.services.knowledge import (
    KnowledgeServiceError,
    create_source,
    import_text_document,
    review_document,
)


class MockDeepSeek:
    provider = "deepseek"
    model = "deepseek-v4-flash"
    configured = True

    def __init__(self, content: dict[str, Any] | None = None, *, timeout: bool = False):
        self.content = content
        self.timeout = timeout
        self.calls = 0
        self.last_user_prompt = ""

    def complete_json(self, *, system_prompt: str, user_prompt: str) -> AICompletion:
        del system_prompt
        self.calls += 1
        self.last_user_prompt = user_prompt
        if self.timeout:
            raise AIProviderError("mock provider timeout")
        return AICompletion(
            content=json.dumps(self.content, ensure_ascii=False),
            input_tokens=120,
            output_tokens=80,
        )


def _create_sensor_failure(api_context: dict[str, Any]) -> str:
    now = datetime.now(timezone.utc).isoformat()
    response = api_context["client"].post(
        "/api/v1/device/logs",
        headers=api_context["headers"],
        json={
            "level": "error",
            "message": "SENSOR_READ_FAILED test event",
            "event_code": "SENSOR_READ_FAILED",
            "occurred_at": now,
            "is_test_data": True,
        },
    )
    assert response.status_code == 201
    diagnosis = api_context["client"].post(
        "/api/v1/diagnosis/devices/phase2-test-device/run",
        headers=api_context["headers"],
        json={"lookback_seconds": 60},
    )
    assert diagnosis.status_code == 201
    return diagnosis.json()["id"]


def _deepseek_settings(**overrides: Any) -> Settings:
    values: dict[str, Any] = {
        "_env_file": None,
        "ai_enabled": True,
        "ai_transport": "openai-compatible",
        "ai_provider": "deepseek",
        "ai_base_url": "https://api.deepseek.com",
        "ai_model": "deepseek-v4-flash",
        "ai_thinking_enabled": False,
        "ai_api_key": "phase95-test-key-not-for-production",
        "ai_require_knowledge": False,
        "ai_max_retries": 0,
    }
    values.update(overrides)
    return Settings(**values)


def _structured_output(diagnosis: DiagnosisResult) -> dict[str, Any]:
    match = diagnosis.matched_rules[0]
    evidence = match["evidence"][0]
    return {
        "error_type": match["error_type"],
        "summary": "Mock DeepSeek 只补充自然语言解释。",
        "evidence": [f"{evidence['fact']}: {evidence['observed_value']}"],
        "possible_causes": [],
        "steps": ["继续执行确定性故障树步骤。"],
        "hint_level": 1,
        "need_teacher_help": False,
        "limitations": ["这是不调用真实 API 的自动化测试。"],
    }


def test_deepseek_profile_is_disabled_without_key_and_forces_non_thinking(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = Settings(_env_file=None)
    assert settings.ai_provider == "deepseek"
    assert settings.ai_model == "deepseek-v4-flash"
    assert settings.ai_base_url == "https://api.deepseek.com"
    assert settings.ai_thinking_enabled is False
    assert settings.ai_configured is False
    assert get_ai_status(settings).provider_configured is False

    configured = _deepseek_settings()
    client = build_ai_client(configured)
    assert isinstance(client, OpenAICompatibleClient)
    payload = client.build_request_payload(
        system_prompt="system",
        user_prompt="user",
    )
    assert payload["model"] == "deepseek-v4-flash"
    assert payload["thinking"] == {"type": "disabled"}
    assert payload["max_tokens"] == configured.ai_output_token_limit

    monkeypatch.setenv("AI_MAX_INPUT_TOKENS", "3210")
    monkeypatch.setenv("AI_MAX_OUTPUT_TOKENS", "765")
    monkeypatch.setenv("AI_DAILY_BUDGET_CNY", "4.5")
    aliased = Settings(_env_file=None)
    assert aliased.ai_input_token_limit == 3210
    assert aliased.ai_output_token_limit == 765
    assert aliased.ai_daily_budget == 4.5

    with pytest.raises(ValidationError):
        Settings(_env_file=None, ai_model="deepseek-v4-pro")
    with pytest.raises(ValidationError):
        Settings(_env_file=None, ai_thinking_enabled=True)
    with pytest.raises(ValidationError):
        Settings(_env_file=None, ai_base_url="https://invalid.example/v1")


def test_safe_context_removes_identity_secrets_and_unrelated_logs() -> None:
    context = {
        "device_id": "ESP32-student-20260001",
        "evaluated_at": "2026-07-25T10:00:00+00:00",
        "last_seen_at": "2026-07-25T09:59:55+00:00",
        "studentName": "张同学",
        "student_id": "20260001",
        "class": "计科2班",
        "device_token": "device-secret-value",
        "database_password": "db-secret-value",
        "wifi_password": "wifi-secret-value",
        "teacher_private_note": "教师私人备注内容",
        "logs": [
            {
                "id": "unrelated",
                "level": "info",
                "message": "unrelated historical boot log",
                "event_code": "BOOT",
                "occurred_at": "2026-07-25T09:00:00+00:00",
            },
            {
                "id": "evidence-log",
                "level": "error",
                "message": (
                    "学生姓名: 张同学 学号: 20260001 "
                    "Authorization: Bearer device-secret-value "
                    "Wi-Fi密码: wifi-secret-value"
                ),
                "event_code": "SENSOR_READ_FAILED",
                "occurred_at": "2026-07-25T09:59:50+00:00",
            },
        ],
        "readings": [
            {
                "id": "reading-1",
                "sensor_type": "test-sensor",
                "metric_key": "temperature",
                "value": 20,
                "unit": "C",
                "observed_at": "2026-07-25T09:59:40+00:00",
            },
            {
                "id": "reading-2",
                "sensor_type": "test-sensor",
                "metric_key": "temperature",
                "value": 22,
                "unit": "C",
                "observed_at": "2026-07-25T09:59:50+00:00",
            },
        ],
        "heartbeats": [
            {"observed_at": "2026-07-25T09:59:55+00:00"},
        ],
    }
    diagnosis = DiagnosisResult(
        id="diagnosis-phase95",
        device_id="internal-device-id",
        evaluated_at=datetime.now(timezone.utc),
        ruleset_version="test",
        ruleset_hash="hash",
        input_fingerprint="fingerprint",
        matched_rules=[
            {
                "rule_id": "sensor-read",
                "error_type": "SENSOR_READ_FAILED",
                "summary": "test",
                "evidence": [
                    {
                        "fact": "log_event_count",
                        "observed_value": 1,
                        "details": [{"log_id": "evidence-log"}],
                    }
                ],
            }
        ],
        evidence=[],
        context_snapshot=context,
        is_test_data=True,
    )
    settings = Settings(_env_file=None, ai_max_log_items=3)
    reference = AIKnowledgeReference(
        chunk_id="chunk-1",
        source_key="test-source",
        source_title="教师私人备注: 教师私人备注内容",
        source_type="verified_case",
        source_uri="private://teacher/path",
        source_version="test-v1",
        locator={"section": "test"},
        content="关键排查知识。邮箱 test@example.com",
        similarity=1,
        is_test_data=True,
    )
    payload = build_safe_ai_input(
        diagnosis,
        [],
        [reference],
        settings,
        episode_id="episode-phase95",
        user_question="API Key: api-secret-value 应该怎么排查？",
    )
    serialized = json.dumps(payload.model_dump(mode="json"), ensure_ascii=False)
    for secret in (
        "张同学",
        "20260001",
        "计科2班",
        "device-secret-value",
        "db-secret-value",
        "wifi-secret-value",
        "教师私人备注内容",
        "api-secret-value",
        "test@example.com",
        "private://teacher/path",
    ):
        assert secret not in serialized
    assert payload.anonymous_device_id.startswith("anon-")
    assert payload.logs[0]["event_code"] == "SENSOR_READ_FAILED"
    assert "unrelated historical boot log" not in serialized
    assert payload.sensor_readings[0]["sample_count"] == 2
    assert payload.sensor_readings[0]["minimum"] == 20
    assert payload.sensor_readings[0]["maximum"] == 22
    audit = json.dumps(audit_snapshot(payload), ensure_ascii=False)
    assert "device-secret-value" not in audit
    assert "phase9.5-allowlist-v1" in audit


def test_single_deepseek_route_cache_and_timeout_fallback(
    api_context: dict[str, Any],
) -> None:
    diagnosis_id = _create_sensor_failure(api_context)
    settings = _deepseek_settings()
    with api_context["session_factory"]() as db:
        diagnosis = db.get(DiagnosisResult, diagnosis_id)
        device = db.query(Device).one()
        assert diagnosis is not None
        mock = MockDeepSeek(_structured_output(diagnosis))
        first = explain_diagnosis(
            db,
            device,
            diagnosis,
            settings,
            ai_client=mock,
            embedding_client=DisabledEmbeddingClient(),
            user_question="请解释这个故障。",
        )
        second = explain_diagnosis(
            db,
            device,
            diagnosis,
            settings,
            ai_client=mock,
            embedding_client=DisabledEmbeddingClient(),
            user_question="请解释这个故障。",
        )
        assert first.status == "succeeded"
        assert first.route == "deepseek"
        assert first.route_path == "cache_miss → deepseek_success"
        assert second.enhancement_status == "cache_hit"
        assert second.route_path == "cache_hit"
        assert mock.calls == 1

        timeout = MockDeepSeek(timeout=True)
        failed = explain_diagnosis(
            db,
            device,
            diagnosis,
            settings,
            ai_client=timeout,
            embedding_client=DisabledEmbeddingClient(),
            user_question="这是另一个不会命中缓存的问题。",
        )
        assert failed.status == "failed"
        assert failed.mode == "rules_only"
        assert failed.route_path == (
            "cache_miss → deepseek_failed → deterministic_fallback"
        )
        record = db.get(AICallRecord, failed.call_record_id)
        assert record is not None
        assert record.error_message == "AI_PROVIDER_TIMEOUT"
        assert record.route_path == failed.route_path


def test_formal_knowledge_governance_and_rag_status_filter(
    api_context: dict[str, Any],
) -> None:
    settings = Settings(_env_file=None)
    with api_context["session_factory"]() as db:
        source = create_source(
            db,
            KnowledgeSourceCreate(
                source_key="phase95-official-source",
                source_type="official_hardware",
                title="明确标记的自动化正式资料夹具",
                source_uri="fixture://official/datasheet",
                version="fixture-v1",
                authorization_scope="仅用于自动化测试",
                metadata={"fixture": True},
                is_test_data=False,
            ),
        )
        document = import_text_document(
            db,
            source.id,
            KnowledgeTextImportRequest(
                title="官方资料自动化测试节选",
                content="SENSOR_READ_FAILED 官方资料测试内容",
                locator_prefix={"section": "fixture-section"},
                metadata={"applicable_hardware": ["fixture-board-v1"]},
                organizer_ref="phase95-organizer",
                is_test_data=False,
            ),
            settings,
        )
        assert document.review_status == "draft"
        assert document.chunks[0].metadata["applicable_hardware"] == [
            "fixture-board-v1"
        ]
        with pytest.raises(KnowledgeServiceError) as direct_approval:
            review_document(
                db,
                document.id,
                KnowledgeReviewRequest(
                    decision="approved",
                    reviewer_role="formal_approver",
                    reviewer_ref="phase95-formal-approver",
                ),
            )
        assert direct_approval.value.code == "INVALID_KNOWLEDGE_REVIEW_TRANSITION"

        for decision, role, reviewer in (
            ("pending", "organizer", "phase95-organizer"),
            (
                "technical_reviewed",
                "technical_reviewer",
                "phase95-technical-reviewer",
            ),
            ("approved", "formal_approver", "phase95-formal-approver"),
        ):
            review_document(
                db,
                document.id,
                KnowledgeReviewRequest(
                    decision=decision,
                    reviewer_role=role,
                    reviewer_ref=reviewer,
                ),
            )
            current = db.get(KnowledgeDocument, document.id)
            assert current is not None
            current_status = current.review_status
            result = hybrid_retrieve(
                db,
                "SENSOR_READ_FAILED",
                settings,
                DisabledEmbeddingClient(),
                include_test_data=False,
            )
            assert bool(result.references) is (current_status == "approved")

        stored = db.get(KnowledgeDocument, document.id)
        assert stored is not None
        for status in (
            "draft",
            "pending",
            "technical_reviewed",
            "rejected",
            "withdrawn",
            "superseded",
        ):
            stored.review_status = status
            for chunk in stored.chunks:
                chunk.review_status = status
            db.commit()
            result = hybrid_retrieve(
                db,
                "SENSOR_READ_FAILED",
                settings,
                DisabledEmbeddingClient(),
                include_test_data=False,
            )
            assert result.references == []

        ai_draft = import_text_document(
            db,
            source.id,
            KnowledgeTextImportRequest(
                title="AI 案例草稿",
                content="AI generated draft fixture",
                locator_prefix={"section": "ai-draft"},
                metadata={"applicable_hardware": ["fixture-board-v1"]},
                organizer_ref="phase95-ai-draft-organizer",
                content_origin="ai_generated",
            ),
            settings,
        )
        assert ai_draft.review_status == "draft"
        assert ai_draft.chunks[0].metadata["content_origin"] == "ai_generated"

        case_source = create_source(
            db,
            KnowledgeSourceCreate(
                source_key="phase95-verified-case",
                source_type="verified_case",
                title="明确标记的自动化故障案例夹具",
                source_uri="fixture://cases/sensor",
                version="fixture-v1",
                authorization_scope="仅用于自动化测试",
                is_test_data=False,
            ),
        )
        with pytest.raises(KnowledgeServiceError) as missing_case_fields:
            import_text_document(
                db,
                case_source.id,
                KnowledgeTextImportRequest(
                    title="缺失治理字段的案例",
                    content="missing governed case fields",
                    metadata={"applicable_hardware": ["fixture-board-v1"]},
                    organizer_ref="phase95-case-organizer",
                ),
                settings,
            )
        assert missing_case_fields.value.code == "FINAL_FIX_ACTION_REQUIRED"
        governed_case = import_text_document(
            db,
            case_source.id,
            KnowledgeTextImportRequest(
                title="完整治理字段案例",
                content="governed verified case fixture",
                metadata={
                    "applicable_hardware": ["fixture-board-v1"],
                    "final_fix_action": "重新连接测试夹具后恢复",
                    "root_cause_confidence": "high",
                },
                organizer_ref="phase95-case-organizer",
            ),
            settings,
        )
        assert governed_case.chunks[0].metadata["final_fix_action"]
        assert governed_case.chunks[0].metadata["root_cause_confidence"] == "high"
