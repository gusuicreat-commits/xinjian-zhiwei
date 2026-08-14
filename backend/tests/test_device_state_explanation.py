from datetime import datetime, timezone

from app.models.device import Device
from app.models.device_log import DeviceLog
from app.models.diagnosis_result import DiagnosisResult
from app.models.sensor_reading import SensorReading
from app.services.device_state_explanation import build_device_state_explanation


def _device(*, last_seen_at: datetime | None = None) -> Device:
    return Device(
        device_key="student-explanation-test",
        display_name="解释层测试设备",
        device_type="test-fixture",
        token_hash="not-used",
        last_seen_at=last_seen_at,
    )


def _diagnosis(*error_codes: str) -> DiagnosisResult:
    now = datetime.now(timezone.utc)
    return DiagnosisResult(
        device_id="device-record",
        evaluated_at=now,
        ruleset_version="test-v1",
        ruleset_hash="a" * 64,
        input_fingerprint="b" * 64,
        matched_rules=[
            {
                "rule_id": f"rule-{index}",
                "error_type": error_code,
                "priority": 100 - index,
                "summary": "测试规则命中",
                "evidence": [{"fact": "log_event_count", "observed_value": 1, "details": []}],
            }
            for index, error_code in enumerate(error_codes)
        ],
        evidence=[],
        context_snapshot={},
        is_test_data=True,
    )


def test_simple_error_uses_deterministic_student_copy_and_keeps_raw_facts() -> None:
    now = datetime.now(timezone.utc)
    log = DeviceLog(
        device_id="device-record",
        level="error",
        message="I2C ACK FAILED",
        event_code="SENSOR_READ_FAILED",
        occurred_at=now,
        sensor_snapshot={"retry_count": 3},
        raw_payload={"event_code": "SENSOR_READ_FAILED"},
        is_test_data=True,
    )
    reading = SensorReading(
        device_id="device-record",
        sensor_type="temperature",
        metric_key="temperature",
        value=22.5,
        unit="°C",
        observed_at=now,
        metadata_json={},
        raw_payload={},
        is_test_data=True,
    )

    result = build_device_state_explanation(
        device=_device(last_seen_at=now),
        device_status="online",
        diagnosis=_diagnosis("SENSOR_READ_FAILED"),
        guidance=[],
        logs=[log],
        readings=[reading],
    )

    assert result.source == "rule"
    assert result.status_title == "温度传感器读取异常"
    assert "开发板仍在线" in result.status_summary
    assert result.technical_details["error_code"] == "SENSOR_READ_FAILED"
    assert result.technical_details["retry_count"] == 3
    assert result.technical_details["logs"][0]["message"] == "I2C ACK FAILED"
    assert result.technical_details["sensor_readings"][0]["value"] == 22.5


def test_validated_ai_copy_can_only_replace_student_prose() -> None:
    result = build_device_state_explanation(
        device=_device(last_seen_at=datetime.now(timezone.utc)),
        device_status="online",
        diagnosis=_diagnosis("SENSOR_READ_FAILED", "VALUE_OUT_OF_RANGE"),
        guidance=[],
        logs=[],
        readings=[],
        ai_output={
            "summary": "开发板在线，但传感器通信和数值均出现异常。",
            "possible_causes": [{"cause": "传感器通信链路需要检查"}],
            "steps": ["先检查接线和实验配置。"],
            "error_type": "SENSOR_READ_FAILED",
        },
    )

    assert result.source == "ai"
    assert result.status_summary == "开发板在线，但传感器通信和数值均出现异常。"
    assert result.next_step == "先检查接线和实验配置。"
    assert result.technical_details["error_codes"] == [
        "SENSOR_READ_FAILED",
        "VALUE_OUT_OF_RANGE",
    ]


def test_provider_absence_still_returns_complete_offline_explanation() -> None:
    result = build_device_state_explanation(
        device=_device(),
        device_status="offline",
        diagnosis=None,
        guidance=[],
        logs=[],
        readings=[],
        ai_output=None,
    )

    assert result.source == "rule"
    assert result.status_title == "设备当前已离线"
    assert result.status_summary
    assert result.meaning
    assert result.next_step
