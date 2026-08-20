from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any

from app.ai.clients import (
    AICompletion,
    AIProviderError,
    DisabledEmbeddingClient,
    OpenAICompatibleClient,
)
from app.core.config import Settings
from app.core.security import hash_password
from app.models import AICallRecord, Device, DiagnosisEpisode, DiagnosisResult, User
from app.services.ai_diagnosis import explain_diagnosis
from app.services.rbac import assign_role, ensure_rbac_catalog


class SequenceAI:
    provider = "phase9-mock-provider"
    model = "phase9-mock-model"
    configured = True

    def __init__(self, outcomes: list[dict[str, Any] | Exception | str]) -> None:
        self.outcomes = outcomes
        self.calls = 0

    def complete_json(self, *, system_prompt: str, user_prompt: str) -> AICompletion:
        assert "不得覆盖" in system_prompt
        assert "output_language" in user_prompt
        outcome = self.outcomes[min(self.calls, len(self.outcomes) - 1)]
        self.calls += 1
        if isinstance(outcome, Exception):
            raise outcome
        content = outcome if isinstance(outcome, str) else json.dumps(outcome, ensure_ascii=False)
        return AICompletion(content=content, input_tokens=40, output_tokens=25)


class CapturingOpenAICompatibleClient(OpenAICompatibleClient):
    def __init__(self) -> None:
        super().__init__(
            provider="phase9-test-provider",
            base_url="https://invalid.example/v1",
            model="phase9-test-model",
            api_key="test-only-not-a-real-key",
            timeout_seconds=1,
            max_retries=0,
            max_output_tokens=37,
        )
        self.payload: dict[str, Any] | None = None

    def _post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        assert path == "/chat/completions"
        self.payload = payload
        return {
            "choices": [{"message": {"content": "{}"}}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1},
        }


def _post_heartbeat(api_context: dict[str, Any], observed_at: datetime) -> None:
    response = api_context["client"].post(
        "/api/v1/device/heartbeat",
        headers=api_context["headers"],
        json={"observed_at": observed_at.isoformat(), "is_test_data": True},
    )
    assert response.status_code == 201


def _post_sensor_failure(api_context: dict[str, Any], occurred_at: datetime) -> None:
    response = api_context["client"].post(
        "/api/v1/device/logs",
        headers=api_context["headers"],
        json={
            "level": "error",
            "message": "Phase 9 synthetic episode acceptance",
            "event_code": "SENSOR_READ_FAILED",
            "occurred_at": occurred_at.isoformat(),
            "is_test_data": True,
        },
    )
    assert response.status_code == 201


def _run_diagnosis(
    api_context: dict[str, Any],
    *,
    lookback_seconds: int = 3600,
    experiment_template: dict[str, Any] | None = None,
) -> dict[str, Any]:
    body: dict[str, Any] = {"lookback_seconds": lookback_seconds}
    if experiment_template is not None:
        body["experiment_template"] = experiment_template
    response = api_context["client"].post(
        "/api/v1/diagnosis/devices/phase2-test-device/run",
        headers=api_context["headers"],
        json=body,
    )
    assert response.status_code == 201
    return response.json()


def _valid_ai_output(diagnosis: DiagnosisResult) -> dict[str, Any]:
    match = diagnosis.matched_rules[0]
    item = match["evidence"][0]
    return {
        "error_type": match["error_type"],
        "summary": "仅用于 Phase 9 Mock 验收的结构化解释。",
        "evidence": [f"{item['fact']}: {item['observed_value']}"],
        "possible_causes": [],
        "steps": ["继续执行确定性排查步骤。"],
        "hint_level": 1,
        "need_teacher_help": False,
        "limitations": ["Mock 输出不是正式专业知识。"],
    }


def _low_confidence_diagnosis(api_context: dict[str, Any]) -> str:
    _post_sensor_failure(api_context, datetime.now(timezone.utc))
    return _run_diagnosis(api_context, lookback_seconds=60)["id"]


def _ai_settings(**overrides: Any) -> Settings:
    values: dict[str, Any] = {
        "ai_transport": "openai-compatible",
        "ai_provider": "phase9-mock-provider",
        "ai_base_url": "https://invalid.example/v1",
        "ai_model": "phase9-mock-model",
        "ai_api_key": "test-only-not-a-real-key",
        "ai_require_knowledge": False,
        "ai_max_retries": 0,
    }
    values.update(overrides)
    return Settings(**values)


def test_episode_aggregates_five_failures_resolves_and_separates_new_error(
    api_context: dict[str, Any],
) -> None:
    now = datetime.now(timezone.utc)
    _post_heartbeat(api_context, now)
    first_started = None
    latest_diagnosis_id = ""
    for index in range(5):
        _post_sensor_failure(api_context, now - timedelta(minutes=10, seconds=index))
        latest_diagnosis_id = _run_diagnosis(api_context)["id"]
        with api_context["session_factory"]() as db:
            episodes = db.query(DiagnosisEpisode).all()
            assert len(episodes) == 1
            first_started = first_started or episodes[0].started_at
            assert episodes[0].started_at == first_started
    with api_context["session_factory"]() as db:
        episode = db.query(DiagnosisEpisode).one()
        assert episode.failure_count == 5
        assert episode.last_diagnosis_result_id == latest_diagnosis_id
        assert episode.last_seen_at >= episode.started_at

    resolved = api_context["client"].post(
        f"/api/v1/student/diagnoses/{latest_diagnosis_id}/feedback",
        headers=api_context["headers"],
        json={"action": "resolved", "note": "synthetic Phase 9 recovery"},
    )
    assert resolved.status_code == 201
    with api_context["session_factory"]() as db:
        assert db.query(DiagnosisEpisode).one().status == "resolved"

    reading = api_context["client"].post(
        "/api/v1/device/readings",
        headers=api_context["headers"],
        json={
            "sensor_type": "synthetic-test-sensor",
            "metric_key": "temperature",
            "value": 99,
            "unit": "test-unit",
            "observed_at": datetime.now(timezone.utc).isoformat(),
            "is_test_data": True,
        },
    )
    assert reading.status_code == 201
    ranged = _run_diagnosis(
        api_context,
        lookback_seconds=5,
        experiment_template={
            "template_id": "DHT11",
            "metric_ranges": {"temperature": {"minimum": 0, "maximum": 50}},
        },
    )
    assert ranged["matches"][0]["error_type"] == "VALUE_OUT_OF_RANGE"
    with api_context["session_factory"]() as db:
        episodes = db.query(DiagnosisEpisode).order_by(DiagnosisEpisode.started_at).all()
        assert len(episodes) == 2
        assert episodes[0].status == "resolved"
        assert episodes[1].primary_error_code == "VALUE_OUT_OF_RANGE"


def test_deterministic_diagnosis_is_complete_for_known_online_failure(
    api_context: dict[str, Any],
) -> None:
    now = datetime.now(timezone.utc)
    _post_heartbeat(api_context, now)
    _post_sensor_failure(api_context, now)
    result = _run_diagnosis(api_context, lookback_seconds=60)
    assert [item["error_type"] for item in result["matches"]] == ["SENSOR_READ_FAILED"]
    core = result["deterministic_result"]
    explanation = result["explanation"]
    assert core["confidence"] >= 0.65
    assert core["evidence"]
    assert explanation["possible_causes"]
    assert explanation["steps"]
    assert explanation["hint_level"] >= 1
    assert isinstance(explanation["need_teacher_help"], bool)
    assert explanation["limitations"]
    assert result["ai_enhancement"]["status"] == "disabled"
    assert "必须配置 AI" not in json.dumps(result, ensure_ascii=False)
    with api_context["session_factory"]() as db:
        diagnosis = db.get(DiagnosisResult, result["id"])
        device = db.query(Device).one()
        assert diagnosis is not None
        fake = SequenceAI([_valid_ai_output(diagnosis)])
        decision = explain_diagnosis(
            db,
            device,
            diagnosis,
            _ai_settings(),
            ai_clients=[("local", fake)],
            embedding_client=DisabledEmbeddingClient(),
        )
        assert decision.status == "skipped"
        assert decision.trigger_reason == "DETERMINISTIC_RESULT_SUFFICIENT"
        assert fake.calls == 0


def test_deterministic_offline_and_out_of_range_are_distinct(
    api_context: dict[str, Any],
) -> None:
    offline = _run_diagnosis(api_context, lookback_seconds=1)
    assert offline["matches"][0]["error_type"] == "DEVICE_OFFLINE"
    assert offline["explanation"]["possible_causes"]
    assert offline["explanation"]["steps"]


def test_dashboard_refresh_and_teacher_statistics_do_not_trigger_ai(
    api_context: dict[str, Any],
) -> None:
    _low_confidence_diagnosis(api_context)
    with api_context["session_factory"]() as db:
        assert db.query(AICallRecord).count() == 0
    for _ in range(2):
        response = api_context["client"].get(
            "/api/v1/student/dashboard", headers=api_context["headers"]
        )
        assert response.status_code == 200
    with api_context["session_factory"]() as db:
        roles = ensure_rbac_catalog(db)
        admin = User(
            username="phase9-dashboard-admin",
            display_name="Phase 9 合成管理员",
            password_hash=hash_password("synthetic-password", iterations=1_000),
            is_test_data=True,
        )
        db.add(admin)
        db.flush()
        assign_role(db, admin, roles["admin"])
        db.commit()
    login = api_context["client"].post(
        "/api/v1/auth/session",
        json={
            "username": "phase9-dashboard-admin",
            "password": "synthetic-password",
        },
    )
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    assert (
        api_context["client"].get("/api/v1/teacher/dashboard", headers=headers).status_code == 200
    )
    with api_context["session_factory"]() as db:
        assert db.query(AICallRecord).count() == 0


def test_local_route_success_and_local_failure_falls_back_without_500(
    api_context: dict[str, Any],
) -> None:
    diagnosis_id = _low_confidence_diagnosis(api_context)
    with api_context["session_factory"]() as db:
        diagnosis = db.get(DiagnosisResult, diagnosis_id)
        device = db.query(Device).one()
        assert diagnosis is not None
        valid = SequenceAI([_valid_ai_output(diagnosis)])
        success = explain_diagnosis(
            db,
            device,
            diagnosis,
            _ai_settings(),
            ai_clients=[("local", valid)],
            embedding_client=DisabledEmbeddingClient(),
        )
        assert success.enhancement_status == "local_success"
        assert success.route == "local"
        record = db.get(AICallRecord, success.call_record_id)
        assert record is not None
        assert record.episode_id is not None
        assert record.diagnosis_result_id == diagnosis.id
        assert record.provider == valid.provider
        assert record.model == valid.model
        assert record.transport == "injected-test"
        assert record.prompt_version == "phase9.5-v1"
        assert record.attempt_count == 1
        assert record.input_tokens == 40
        assert record.output_tokens == 25
        assert record.latency_ms is not None
        assert record.validation_status == "passed"
        audit_text = json.dumps(record.input_snapshot, ensure_ascii=False)
        assert "api_key" not in audit_text.lower()
        assert "authorization" not in audit_text.lower()

        timeout = SequenceAI([AIProviderError("synthetic local timeout")])
        failed = explain_diagnosis(
            db,
            device,
            diagnosis,
            _ai_settings(ai_prompt_version="phase9-timeout-case"),
            ai_clients=[("local", timeout)],
            embedding_client=DisabledEmbeddingClient(),
            user_question="使用不同指纹验证本地超时降级",
        )
        assert failed.enhancement_status == "failed_fallback"
        assert failed.mode == "rules_only"
        failed_record = db.get(AICallRecord, failed.call_record_id)
        assert failed_record is not None
        assert failed_record.route == "local"
        assert failed_record.validation_status == "failed"
        assert failed_record.fallback_reason == "DETERMINISTIC_TEMPLATE"


def test_local_failure_can_route_to_cloud_mock(api_context: dict[str, Any]) -> None:
    diagnosis_id = _low_confidence_diagnosis(api_context)
    with api_context["session_factory"]() as db:
        diagnosis = db.get(DiagnosisResult, diagnosis_id)
        device = db.query(Device).one()
        assert diagnosis is not None
        local = SequenceAI([AIProviderError("synthetic local timeout")])
        cloud = SequenceAI([_valid_ai_output(diagnosis)])
        result = explain_diagnosis(
            db,
            device,
            diagnosis,
            _ai_settings(),
            ai_clients=[("local", local), ("cloud", cloud)],
            embedding_client=DisabledEmbeddingClient(),
        )
        assert result.enhancement_status == "cloud_success"
        record = db.get(AICallRecord, result.call_record_id)
        assert record is not None
        assert record.route == "cloud"
        assert record.fallback_reason == "LOCAL_FAILED_CLOUD_USED"
        assert local.calls == 1
        assert cloud.calls == 1


def test_invalid_json_retries_then_fails_closed(api_context: dict[str, Any]) -> None:
    diagnosis_id = _low_confidence_diagnosis(api_context)
    with api_context["session_factory"]() as db:
        diagnosis = db.get(DiagnosisResult, diagnosis_id)
        device = db.query(Device).one()
        assert diagnosis is not None
        invalid = SequenceAI(["{invalid-json"])
        result = explain_diagnosis(
            db,
            device,
            diagnosis,
            _ai_settings(ai_max_retries=1),
            ai_clients=[("local", invalid)],
            embedding_client=DisabledEmbeddingClient(),
        )
        assert result.status == "failed"
        assert invalid.calls == 2
        record = db.get(AICallRecord, result.call_record_id)
        assert record is not None
        assert record.attempt_count == 2
        assert record.error_code == "AI_OUTPUT_OR_PROVIDER_FAILED"
        assert record.validation_status == "failed"
        assert "API" not in (record.error_message or "")


def test_input_and_per_call_budget_limits_are_audited(
    api_context: dict[str, Any],
) -> None:
    diagnosis_id = _low_confidence_diagnosis(api_context)
    with api_context["session_factory"]() as db:
        diagnosis = db.get(DiagnosisResult, diagnosis_id)
        device = db.query(Device).one()
        assert diagnosis is not None
        fake = SequenceAI([_valid_ai_output(diagnosis)])
        token_limited = explain_diagnosis(
            db,
            device,
            diagnosis,
            _ai_settings(ai_input_token_limit=1),
            ai_clients=[("local", fake)],
            embedding_client=DisabledEmbeddingClient(),
        )
        assert token_limited.status == "skipped"
        assert fake.calls == 0
        token_record = db.get(AICallRecord, token_limited.call_record_id)
        assert token_record is not None
        assert token_record.error_code == "INPUT_TOKEN_LIMIT"

        budget_limited = explain_diagnosis(
            db,
            device,
            diagnosis,
            _ai_settings(
                ai_prompt_version="phase9-budget-case",
                ai_input_cost_per_1k_tokens=1,
                ai_output_cost_per_1k_tokens=1,
                ai_max_cost_per_call=0,
            ),
            ai_clients=[("local", fake)],
            embedding_client=DisabledEmbeddingClient(),
            user_question="使用不同指纹验证单次预算",
        )
        assert budget_limited.status == "skipped"
        budget_record = db.get(AICallRecord, budget_limited.call_record_id)
        assert budget_record is not None
        assert budget_record.error_code == "PER_CALL_BUDGET_LIMIT"
        assert fake.calls == 0


def test_episode_hourly_and_daily_limits_degrade_without_blocking_template(
    api_context: dict[str, Any],
) -> None:
    diagnosis_id = _low_confidence_diagnosis(api_context)
    with api_context["session_factory"]() as db:
        diagnosis = db.get(DiagnosisResult, diagnosis_id)
        device = db.query(Device).one()
        assert diagnosis is not None
        fake = SequenceAI([_valid_ai_output(diagnosis)])
        first = explain_diagnosis(
            db,
            device,
            diagnosis,
            _ai_settings(ai_calls_per_device_hour=1),
            ai_clients=[("local", fake)],
            embedding_client=DisabledEmbeddingClient(),
        )
        assert first.status == "succeeded"
        hourly = explain_diagnosis(
            db,
            device,
            diagnosis,
            _ai_settings(ai_calls_per_device_hour=1),
            ai_clients=[("local", fake)],
            embedding_client=DisabledEmbeddingClient(),
            user_question="不同问题绕过缓存并验证小时限流",
        )
        assert hourly.status == "skipped"
        hourly_record = db.get(AICallRecord, hourly.call_record_id)
        assert hourly_record is not None
        assert hourly_record.error_code == "DEVICE_HOURLY_CALL_LIMIT"
        assert hourly.deterministic_result

        daily = explain_diagnosis(
            db,
            device,
            diagnosis,
            _ai_settings(
                ai_calls_per_device_hour=10,
                ai_calls_per_episode=10,
                ai_daily_budget=0,
            ),
            ai_clients=[("local", fake)],
            embedding_client=DisabledEmbeddingClient(),
            user_question="不同问题验证每日预算",
        )
        daily_record = db.get(AICallRecord, daily.call_record_id)
        assert daily_record is not None
        assert daily_record.error_code == "DAILY_BUDGET_LIMIT"

        episode = explain_diagnosis(
            db,
            device,
            diagnosis,
            _ai_settings(
                ai_calls_per_device_hour=10,
                ai_calls_per_episode=1,
            ),
            ai_clients=[("local", fake)],
            embedding_client=DisabledEmbeddingClient(),
            user_question="不同问题验证 Episode 限流",
        )
        episode_record = db.get(AICallRecord, episode.call_record_id)
        assert episode_record is not None
        assert episode_record.error_code == "EPISODE_CALL_LIMIT"


def test_output_token_limit_is_sent_to_compatible_transport() -> None:
    client = CapturingOpenAICompatibleClient()
    client.complete_json(system_prompt="test", user_prompt="test")
    assert client.payload is not None
    assert client.payload["max_tokens"] == 37
