from __future__ import annotations

import json
from copy import deepcopy
from datetime import datetime, timezone
from typing import Any

import httpx
import pytest

from app.ai.clients import AIProviderError, OpenAICompatibleClient
from app.ai.context_sanitizer import (
    anonymous_device_id,
    build_safe_ai_input,
    sanitize_provider_payload,
)
from app.ai.schemas import AIKnowledgeReference
from app.core.config import Settings
from app.models import AICallRecord, Device, DiagnosisResult
from app.services.ai_diagnosis import _explain_diagnosis as explain_diagnosis


def _client() -> OpenAICompatibleClient:
    return OpenAICompatibleClient(
        provider="boundary-test", base_url="https://invalid.example", model="mock",
        api_key="synthetic-key", timeout_seconds=1, max_retries=2,
    )


@pytest.mark.parametrize(
    "usage",
    [[], ["invalid"], "invalid", 0, False,
     {"prompt_tokens": float("nan")}, {"completion_tokens": float("inf")},
     {"prompt_tokens": -1}, {"prompt_tokens": 1.5}, {"prompt_tokens": True},
     {"prompt_tokens": "10"}],
)
def test_malformed_usage_is_a_safe_provider_error(usage: Any, monkeypatch) -> None:
    client = _client()
    monkeypatch.setattr(client, "_post_once", lambda *args, **kwargs: {
        "choices": [{"message": {"content": "{}"}}], "usage": usage,
    })
    for method in (client.complete_json, client.complete_json_once):
        with pytest.raises(AIProviderError):
            method(system_prompt="test", user_prompt="test")


@pytest.mark.parametrize("usage", [None, {}, {"prompt_tokens": 12, "completion_tokens": 3.0}])
def test_optional_and_valid_usage_remain_supported(usage: Any, monkeypatch) -> None:
    client = _client()
    monkeypatch.setattr(client, "_post_once", lambda *args, **kwargs: {
        "choices": [{"message": {"content": "{}"}}], "usage": usage,
    })
    completion = client.complete_json_once(system_prompt="test", user_prompt="test")
    assert completion.content == "{}"
    assert completion.input_tokens == (12 if usage else None)
    assert completion.output_tokens == (3 if usage else None)


def test_single_attempt_transport_does_not_retry(monkeypatch) -> None:
    calls = []

    async def fail(*args, **kwargs):
        calls.append(1)
        raise httpx.ConnectError("synthetic failure")

    monkeypatch.setattr(httpx.AsyncClient, "send", fail)
    client = _client()
    with pytest.raises(AIProviderError):
        client.complete_json_once(system_prompt="test", user_prompt="test")
    assert len(calls) == 1
    calls.clear()
    with pytest.raises(AIProviderError):
        client.complete_json(system_prompt="test", user_prompt="test")
    assert len(calls) == 1  # direct client cannot hide unreserved retries


def test_malformed_usage_falls_back_in_explanation(api_context, monkeypatch) -> None:
    api = api_context["client"]
    headers = api_context["headers"]
    response = api.post("/api/v1/device/logs", headers=headers, json={
        "level": "error", "message": "synthetic Provider regression",
        "event_code": "SENSOR_READ_FAILED", "is_test_data": True,
        "occurred_at": datetime.now(timezone.utc).isoformat(),
    })
    assert response.status_code == 201
    response = api.post(
        "/api/v1/diagnosis/devices/phase2-test-device/run", headers=headers,
        json={"lookback_seconds": 60},
    )
    assert response.status_code == 201
    client = _client()
    calls = []

    def malformed(*args, **kwargs):
        calls.append(1)
        return {"choices": [{"message": {"content": "{}"}}], "usage": ["invalid"]}

    monkeypatch.setattr(client, "_post_once", malformed)
    with api_context["session_factory"]() as db:
        diagnosis = db.get(DiagnosisResult, response.json()["id"])
        device = db.query(Device).one()
        result = explain_diagnosis(
            db, device, diagnosis,
            Settings(_env_file=None, ai_enabled=True, ai_require_knowledge=False,
                     ai_max_retries=0),
            ai_client=client, user_question="请解释当前异常",
        )
        assert calls == [1]
        assert result.status == "failed"
        assert result.mode == "rules_only"
        assert result.deterministic_result is not None
        record = db.get(AICallRecord, result.call_record_id)
        assert record.error_code
        assert "invalid" not in (record.error_message or "")


def test_provider_projection_redacts_nested_secrets_without_changing_references() -> None:
    sources = [f"evidence-{i}" for i in range(60)]
    payload = {
        "discarded": {"password": "hidden-secret", "student_name": "合成学生"},
        "device_status": {"device_id": "ESP32-student-20260001", "status": "online"},
        "knowledge": {"normalState": {
            "api_key": "nested-secret", "teacherPrivateNote": {"text": "私密内容"},
            "threshold": 3, "enabled": True,
        }, "symptom": "hidden-secret nested-secret 合成学生 私密内容"},
        "locked_facts": [{"cause_id": "cause-1", "evidence_refs": sources,
                          "caseId": "case-1", "action_id": "check-1"}],
        "source_ids": sources,
        "note": "password=inline-secret",
    }
    original = deepcopy(payload)
    safe = sanitize_provider_payload(payload, allowed_fields=(
        "device_status", "knowledge", "locked_facts", "source_ids", "note",
    ), trusted_references={
        ("locked_facts", "*", "cause_id"): {"cause-1"},
        ("locked_facts", "*", "evidence_refs", "*"): set(sources),
        ("locked_facts", "*", "caseId"): {"case-1"},
        ("locked_facts", "*", "action_id"): {"check-1"},
        ("source_ids", "*"): set(sources),
    })
    text = json.dumps(safe, ensure_ascii=False)
    for secret in ("hidden-secret", "nested-secret", "合成学生", "私密内容",
                   "inline-secret", "ESP32-student-20260001"):
        assert secret not in text
    assert "discarded" not in safe
    assert safe["device_status"]["device_id"] == anonymous_device_id("ESP32-student-20260001")
    assert safe["knowledge"]["normalState"] == {"threshold": 3, "enabled": True}
    assert safe["locked_facts"] == original["locked_facts"]
    assert safe["source_ids"] == sources
    assert payload == original


def test_explanation_projection_anonymizes_workflow_and_structured_knowledge() -> None:
    device_id = "ESP32-student-20260001"
    context = {"device_id": device_id, "logs": []}
    record = DiagnosisResult(id="diagnosis-test", context_snapshot=context,
                             matched_rules=[], is_test_data=True)
    reference = AIKnowledgeReference(
        chunk_id="case-1", source_key="case-1", source_title="测试", source_uri=None,
        similarity=1, is_test_data=True,
        content=json.dumps({"caseId": "case-1", "normalState": {
            "api_key": "knowledge-secret", "expected": 3,
        }, "symptom": "knowledge-secret"}),
    )
    state = {"device_status": {"device_id": device_id, "status": "online"},
             "reasoning_summary": "knowledge-secret"}
    payload = build_safe_ai_input(
        record, [], [reference], Settings(_env_file=None), episode_id=None,
        user_question=None, workflow_state=state,
    )
    serialized = payload.model_dump_json()
    assert device_id not in serialized
    assert "knowledge-secret" not in serialized
    assert payload.workflow_state["device_status"]["device_id"] == payload.anonymous_device_id
    assert json.loads(payload.knowledge[0].content)["normalState"] == {"expected": 3}
    assert context["device_id"] == device_id
    assert state["device_status"]["device_id"] == device_id
