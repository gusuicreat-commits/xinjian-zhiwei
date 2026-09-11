from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.diagnosis.lightweight_schemas import (
    AIPolicyDecision,
    DeterministicExplanation,
    DiagnosisCore,
)
from app.models.ai_call_record import AICallRecord
from app.models.diagnosis_episode import DiagnosisEpisode
from app.models.diagnosis_result import DiagnosisResult
from app.models.guidance_history import GuidanceHistory

DETERMINISTIC_FALLBACKS: dict[str, dict[str, list[str]]] = {
    "DEVICE_OFFLINE": {
        "causes": [
            "设备未继续上报心跳或采集数据",
            "设备与服务端之间的通信链路中断",
        ],
        "steps": [
            "确认设备是否仍在运行，并记录最后一次正常上报时间。",
            "检查设备侧网络状态和服务端可达性，不要据此直接判定硬件损坏。",
            "恢复上报后重新运行诊断；若仍离线，请保留日志并请求教师协助。",
        ],
    },
    "VALUE_OUT_OF_RANGE": {
        "causes": [
            "采集值确实超出当前实验模板配置范围",
            "实验范围、单位或指标映射仍需核对",
        ],
        "steps": [
            "核对证据中的采集值、单位以及实验模板上下界。",
            "继续采集多个时间点，区分单次波动与持续越界。",
            "若范围或单位配置无法确认，请保留原始读数并请求教师协助。",
        ],
    },
    "SENSOR_READ_FAILED": {
        "causes": ["传感器数据通路、供电连接或读取时序方向需要继续排查"],
        "steps": [
            "先保留失败日志和当前实验状态。",
            "按照故障树逐级检查通用连接、配置和读取时序。",
            "不要在没有测量证据时直接判定具体器件损坏。",
        ],
    },
}


def build_diagnosis_core(
    diagnosis: DiagnosisResult,
    guidance: list[GuidanceHistory],
    knowledge_chunk_ids: list[str] | None = None,
) -> DiagnosisCore:
    matches = diagnosis.matched_rules
    primary = str(matches[0].get("error_type")) if matches else None
    summary = (
        str(matches[0].get("summary") or primary)
        if matches
        else "当前数据未命中已配置的确定性诊断规则。"
    )
    normal_assessment = (diagnosis.context_snapshot or {}).get("normal_assessment") or {}
    normal_status = normal_assessment.get("status", "unknown")
    if not matches:
        summary = ("当前上报数据满足已配置的心跳、周期、字段与无异常条件；不证明硬件已验证。"
                   if normal_status == "normal" else
                   "正常条件未全部满足，状态待核验；没有异常规则命中不代表正常。")
    evidence = []
    for match in matches:
        for item in match.get("evidence", []):
            evidence.append(f"{item.get('fact')} = {item.get('observed_value')}")
    possible_causes = [
        str(cause.get("title"))
        for item in guidance
        for cause in item.ranked_causes
        if cause.get("title")
    ]
    steps = [str(hint.get("text")) for item in guidance for hint in item.hints if hint.get("text")]
    hint_level = max((item.hint_level for item in guidance), default=1)
    placeholder = any(item.fault_tree_status == "placeholder" for item in guidance)
    fallback = DETERMINISTIC_FALLBACKS.get(primary or "", {})
    if not possible_causes:
        possible_causes = fallback.get("causes", ["现有证据不足，需要继续采集数据并核对实验配置"])
    if not steps:
        steps = fallback.get(
            "steps",
            [
                "保留当前日志、读数和实验配置。",
                "核对异常是否可以稳定复现。",
                "证据不足时请求教师协助，不做具体硬件结论。",
            ],
        )
    confidence = 0.25
    if len(matches) == 1:
        confidence = 0.72
    elif len(matches) > 1:
        confidence = 0.5
    if len(matches) == 1 and guidance and not placeholder:
        confidence = 0.8
    limitations = ["当前规则与阈值仍包含开发阶段示例或待确认参数，不能作为真实硬件专业结论。"]
    if not matches:
        limitations.append("没有匹配规则，不能据此确定故障类型。")
    if not knowledge_chunk_ids:
        limitations.append("没有引用已审核知识片段。")
    return DiagnosisCore(
        diagnosis_result_id=diagnosis.id,
        primary_error_code=primary,
        summary=summary,
        confidence=confidence,
        evidence=list(dict.fromkeys(evidence)),
        possible_causes=list(dict.fromkeys(possible_causes)),
        suggested_steps=list(dict.fromkeys(steps)),
        hint_level=hint_level,
        need_teacher_help=any(item.teacher_intervention_required for item in guidance),
        rule_ids=[str(item.get("rule_id")) for item in matches if item.get("rule_id")],
        knowledge_chunk_ids=knowledge_chunk_ids or [],
        limitations=limitations,
        normal_assessment=normal_assessment,
    )


def render_deterministic_explanation(core: DiagnosisCore) -> DeterministicExplanation:
    return DeterministicExplanation(
        title=core.primary_error_code or "未识别异常",
        summary=core.summary,
        evidence=core.evidence,
        possible_causes=core.possible_causes,
        steps=core.suggested_steps,
        hint_level=core.hint_level,
        need_teacher_help=core.need_teacher_help,
        limitations=core.limitations,
    )


def decide_ai_policy(
    core: DiagnosisCore,
    settings: Settings,
    *,
    episode: DiagnosisEpisode | None = None,
    user_question: str | None = None,
    retrieval_conflict: bool = False,
    teacher_draft_requested: bool = False,
) -> AIPolicyDecision:
    reasons = []
    if user_question:
        reasons.append("USER_QUESTION")
    if teacher_draft_requested:
        reasons.append("TEACHER_DRAFT_REQUEST")
    if core.primary_error_code is None:
        reasons.append("UNKNOWN_ANOMALY")
    if len(core.rule_ids) > 1:
        reasons.append("MULTIPLE_RULES")
    if core.confidence < settings.ai_low_confidence_threshold:
        reasons.append("LOW_CONFIDENCE")
    if retrieval_conflict:
        reasons.append("KNOWLEDGE_CONFLICT")
    if episode and episode.status == "escalated":
        reasons.append("EPISODE_ESCALATED")
    if not reasons:
        return AIPolicyDecision(
            should_call=False, reason="DETERMINISTIC_RESULT_SUFFICIENT", confidence=core.confidence
        )
    return AIPolicyDecision(should_call=True, reason="+".join(reasons), confidence=core.confidence)


def explanation_fingerprint(
    core: DiagnosisCore,
    *,
    prompt_version: str,
    schema_version: str,
    ruleset_version: str,
    fault_tree_version: str | None,
    knowledge_chunk_ids: list[str],
    output_language: str = "zh-CN",
    user_question: str | None = None,
) -> str:
    normalized_core = core.model_dump(mode="json", exclude={"diagnosis_result_id"})
    for key in ("evidence", "rule_ids", "knowledge_chunk_ids"):
        normalized_core[key] = sorted(normalized_core.get(key, []))
    payload = {
        "core": normalized_core,
        "prompt_version": prompt_version,
        "schema_version": schema_version,
        "ruleset_version": ruleset_version,
        "fault_tree_version": fault_tree_version,
        "knowledge_chunk_ids": sorted(knowledge_chunk_ids),
        "output_language": output_language,
        "user_question": user_question.strip() if user_question else None,
    }
    encoded = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


def budget_allowed(
    db: Session,
    device_id: str,
    settings: Settings,
    episode: DiagnosisEpisode | None,
    *,
    projected_call_cost: float | None = None,
) -> tuple[bool, str | None]:
    if (
        settings.ai_max_cost_per_call is not None
        and projected_call_cost is not None
        and projected_call_cost > settings.ai_max_cost_per_call
    ):
        return False, "PER_CALL_BUDGET_LIMIT"
    if episode and episode.ai_call_count >= settings.ai_calls_per_episode:
        return False, "EPISODE_CALL_LIMIT"
    since = datetime.now(timezone.utc) - timedelta(hours=1)
    hourly = (
        db.scalar(
            select(func.count(AICallRecord.id))
            .join(DiagnosisResult, DiagnosisResult.id == AICallRecord.diagnosis_result_id)
            .where(
                DiagnosisResult.device_id == device_id,
                AICallRecord.status.in_(("succeeded", "failed")),
                or_(
                    AICallRecord.cache_status.is_(None),
                    AICallRecord.cache_status != "hit",
                ),
                AICallRecord.created_at >= since,
            )
        )
        or 0
    )
    if hourly >= settings.ai_calls_per_device_hour:
        return False, "DEVICE_HOURLY_CALL_LIMIT"
    if settings.ai_daily_budget is not None:
        day = datetime.now(timezone.utc) - timedelta(days=1)
        spent = (
            db.scalar(
                select(func.coalesce(func.sum(AICallRecord.estimated_cost), 0.0)).where(
                    AICallRecord.created_at >= day,
                    AICallRecord.attempt_count > 0,
                )
            )
            or 0.0
        )
        if float(spent) >= settings.ai_daily_budget:
            return False, "DAILY_BUDGET_LIMIT"
    return True, None


def estimate_ai_cost(input_tokens: int, output_tokens: int, settings: Settings) -> float | None:
    if (
        settings.ai_input_cost_per_1k_tokens is None
        or settings.ai_output_cost_per_1k_tokens is None
    ):
        return None
    return round(
        input_tokens / 1000 * settings.ai_input_cost_per_1k_tokens
        + output_tokens / 1000 * settings.ai_output_cost_per_1k_tokens,
        8,
    )
