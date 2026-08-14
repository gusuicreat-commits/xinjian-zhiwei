from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from app.diagnosis.lightweight_schemas import DeviceStateExplanation
from app.models.device import Device
from app.models.device_log import DeviceLog
from app.models.diagnosis_result import DiagnosisResult
from app.models.guidance_history import GuidanceHistory
from app.models.sensor_reading import SensorReading

STATE_COPY: dict[str, dict[str, str]] = {
    "DEVICE_OFFLINE": {
        "title": "设备当前已离线",
        "summary": "设备已经超过设定时间没有向平台发送心跳。",
        "meaning": "平台暂时无法确认开发板的实时状态，但这本身不能证明硬件已经损坏。",
        "next_step": "请先确认设备是否供电，并检查网络连接后重新观察心跳。",
    },
    "SENSOR_READ_FAILED": {
        "title": "传感器读取异常",
        "summary": "传感器暂时无法正常读取。",
        "meaning": "问题更可能发生在传感器的数据采集或通信环节。",
        "next_step": "请先保留当前接线，按故障树提示检查连接和实验配置。",
    },
    "VALUE_OUT_OF_RANGE": {
        "title": "传感器数值超出实验范围",
        "summary": "当前传感器数值超出实验模板配置的正常范围。",
        "meaning": "这可能是真实波动，也可能与单位、指标映射或实验范围配置有关。",
        "next_step": "请先核对原始数值、单位和实验范围，并继续观察后续读数。",
    },
}


def _value_from_mapping(value: Any, keys: tuple[str, ...]) -> int | None:
    if not isinstance(value, dict):
        return None
    for key in keys:
        candidate = value.get(key)
        if isinstance(candidate, bool):
            continue
        if isinstance(candidate, int) and candidate >= 0:
            return candidate
        if isinstance(candidate, str) and candidate.isdigit():
            return int(candidate)
    for nested_key in ("metadata", "details", "sensor", "diagnostic"):
        nested = _value_from_mapping(value.get(nested_key), keys)
        if nested is not None:
            return nested
    return None


def _retry_count(logs: Iterable[DeviceLog]) -> int | None:
    keys = ("retry_count", "retryCount", "retry", "retries")
    for item in reversed(list(logs)):
        for value in (item.sensor_snapshot, item.raw_payload):
            found = _value_from_mapping(value, keys)
            if found is not None:
                return found
    return None


def _sensor_title(readings: list[SensorReading], fallback: str) -> str:
    if not readings:
        return fallback
    latest = readings[-1]
    identity = f"{latest.sensor_type} {latest.metric_key}".lower()
    if "temp" in identity or "temperature" in identity:
        return fallback.replace("传感器", "温度传感器", 1)
    if "humid" in identity:
        return fallback.replace("传感器", "湿度传感器", 1)
    return fallback


def _rule_copy(
    error_code: str | None, device_status: str, readings: list[SensorReading]
) -> dict[str, str]:
    if error_code in STATE_COPY:
        copy = dict(STATE_COPY[error_code])
        copy["title"] = _sensor_title(readings, copy["title"])
        if error_code == "SENSOR_READ_FAILED" and device_status == "online":
            copy["summary"] = "开发板仍在线，但传感器暂时无法正常读取。"
            copy["meaning"] = (
                "开发板仍能与平台通信，问题更可能发生在传感器通信环节，而不是整个开发板掉线。"
            )
        return copy
    if device_status == "offline":
        return dict(STATE_COPY["DEVICE_OFFLINE"])
    if device_status == "never_seen":
        return {
            "title": "设备尚未上报状态",
            "summary": "平台还没有收到这台设备的有效心跳。",
            "meaning": "目前没有足够数据判断设备是否正常运行。",
            "next_step": "请确认设备已启动并完成首次上报。",
        }
    if error_code:
        return {
            "title": "设备检测到异常",
            "summary": "系统已记录设备异常，并保留了原始错误码。",
            "meaning": "当前错误码尚无已确认的学生态翻译，不能据此猜测具体硬件原因。",
            "next_step": "请展开技术详情核对日志，并请求教师确认该错误码的正式定义。",
        }
    return {
        "title": "设备当前在线",
        "summary": "平台近期收到了设备心跳，当前没有命中已配置的异常规则。",
        "meaning": "这只表示通信正常且示例规则未发现异常，不等同于完整的硬件健康认证。",
        "next_step": "可以继续实验，并留意后续读数和日志变化。",
    }


def _technical_details(
    device: Device,
    device_status: str,
    diagnosis: DiagnosisResult | None,
    guidance: list[GuidanceHistory],
    logs: list[DeviceLog],
    readings: list[SensorReading],
) -> dict[str, Any]:
    matches = list(diagnosis.matched_rules) if diagnosis is not None else []
    retry_count = _retry_count(logs)
    details: dict[str, Any] = {
        "device": {
            "status": device_status,
            "last_seen_at": device.last_seen_at,
            "firmware_version": device.firmware_version,
        },
        "error_code": matches[0].get("error_type") if matches else None,
        "error_codes": list(
            dict.fromkeys(str(item["error_type"]) for item in matches if item.get("error_type"))
        ),
        "logs": [
            {
                "id": item.id,
                "level": item.level,
                "message": item.message,
                "event_code": item.event_code,
                "occurred_at": item.occurred_at,
            }
            for item in logs[-10:]
        ],
        "sensor_readings": [
            {
                "id": item.id,
                "sensor_type": item.sensor_type,
                "metric_key": item.metric_key,
                "value": item.value,
                "unit": item.unit,
                "observed_at": item.observed_at,
            }
            for item in readings[-10:]
        ],
        "rule_hits": matches,
        "fault_tree_evidence": [
            {
                "tree_id": item.fault_tree_id,
                "tree_title": item.fault_tree_title,
                "tree_status": item.fault_tree_status,
                "hint_level": item.hint_level,
                "failure_count": item.failure_count,
                "ranked_causes": item.ranked_causes,
            }
            for item in guidance
        ],
    }
    if retry_count is not None:
        details["retry_count"] = retry_count
    return details


def build_device_state_explanation(
    *,
    device: Device,
    device_status: str,
    diagnosis: DiagnosisResult | None,
    guidance: list[GuidanceHistory],
    logs: list[DeviceLog],
    readings: list[SensorReading],
    ai_output: dict[str, Any] | None = None,
) -> DeviceStateExplanation:
    """Translate confirmed facts; optionally adapt an already validated AI output."""

    matches = list(diagnosis.matched_rules) if diagnosis is not None else []
    primary_error = (
        str(matches[0]["error_type"]) if matches and matches[0].get("error_type") else None
    )
    copy = _rule_copy(primary_error, device_status, readings)
    source = "rule"
    if ai_output:
        summary = ai_output.get("summary")
        steps = ai_output.get("steps") or []
        causes = ai_output.get("possible_causes") or []
        if isinstance(summary, str) and summary.strip():
            copy["summary"] = summary.strip()
            source = "ai"
        if steps and isinstance(steps[0], str):
            copy["next_step"] = steps[0]
        if causes:
            first = causes[0]
            cause = first.get("cause") if isinstance(first, dict) else first
            if isinstance(cause, str) and cause.strip():
                copy["meaning"] = f"结合现有证据，优先排查：{cause.strip()}。"
    return DeviceStateExplanation(
        status_title=copy["title"],
        status_summary=copy["summary"],
        meaning=copy["meaning"],
        next_step=copy["next_step"],
        source=source,
        technical_details=_technical_details(
            device, device_status, diagnosis, guidance, logs, readings
        ),
    )
