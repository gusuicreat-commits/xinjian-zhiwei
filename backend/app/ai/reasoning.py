from __future__ import annotations

import hashlib
import json
import time
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.ai.clients import AIClient, build_ai_client
from app.ai.context_sanitizer import sanitize_text
from app.ai.schemas import AIReasonedCause, AIReasoningResult
from app.core.config import Settings
from app.models.ai_call_record import AICallRecord
from app.models.diagnosis_result import DiagnosisResult

REASONING_PROMPT_VERSION = "evidence-reasoning-v2.1"
REASONING_SYSTEM_PROMPT = """你是受约束的嵌入式实验原因排序器。
error_type 是规则引擎已经确定的事实，不得修改。
只能使用 candidate_causes 中已有的 cause_id，不得创造新故障。
used_evidence_ids 只能选择 evidence_registry 中已有的 id。
next_verification_action 只能逐字选择 allowed_verification_actions 中的 text。
knowledge_constraints 只提供实验定义、正常条件、标准故障映射和已确认案例；
不得将历史案例直接当作本次根因。
使用 high、medium、low、unknown 表示证据支持等级，不得把它表述为统计概率。
证据冲突时 conflict=true，且不得给出 high；资料不足时 conclusion 必须为 unknown。
GPIO_COMMAND_HIGH、GPIO_ACTUAL_LEVEL_HIGH、LED_PHYSICALLY_ON 是不同事实；
命令或来源未验证的 level=1 不能证明实际电平或发光。status=unknown 的观测不能用作已确认事实。
failure_count_in_window 不是 consecutive_failure_count；窗口累计失败不能表述为连续失败。
时间先后不等于因果，不得把候选原因表述为已确认根因。
只返回符合 JSON Schema 的 JSON。"""


def build_evidence_registry(state: dict[str, Any]) -> list[dict[str, str]]:
    """Use the persisted evidence allowlist supplied by the workflow.

    Current diagnosis runs populate this list from ``diagnosis_evidence``.  The
    reasoning layer must not mint aliases such as ``device:status`` or raw log
    IDs, because those values cannot be traced to one immutable evidence row.
    """
    facts: list[dict[str, str]] = []

    def add(evidence_id: str, fact: str, source: str) -> None:
        if not evidence_id or not fact or any(item["id"] == evidence_id for item in facts):
            return
        facts.append({"id": evidence_id, "fact": fact, "source": source})

    for item in state.get("evidence_registry") or []:
        add(
            sanitize_text(item.get("id"), max_chars=100),
            sanitize_text(item.get("fact"), max_chars=300),
            sanitize_text(item.get("source"), max_chars=50),
        )
    return facts[:50]


def _support_level(score: float) -> str:
    return "high" if score >= 0.75 else "medium" if score >= 0.45 else "low"


def _fallback_reasoning(
    state: dict[str, Any], *, limitation: str
) -> AIReasoningResult:
    candidates = list(state.get("fault_tree_candidates") or [])
    evidence = build_evidence_registry(state)
    evidence_ids = [item["id"] for item in evidence]
    actions = list(state.get("allowed_verification_actions") or [])
    if not candidates:
        return AIReasoningResult(
            error_type=state.get("error_type"),
            conclusion="unknown",
            ranked_causes=[],
            summary="现有证据不足以形成候选原因排序。",
            limitations=[limitation],
            missing_evidence=["缺少经过故障树限定的候选原因。"],
            conflict=bool(state.get("evidence_conflict")),
        )
    return AIReasoningResult(
        error_type=state.get("error_type"),
        conclusion="ranked",
        ranked_causes=[
            AIReasonedCause(
                cause_id=str(item.get("cause_id") or ""),
                cause=str(item.get("name") or "未知候选原因"),
                support_level=(
                    "medium"
                    if state.get("evidence_conflict")
                    and _support_level(
                        max(0.0, min(1.0, float(item.get("score") or 0.0)))
                    )
                    == "high"
                    else _support_level(
                        max(0.0, min(1.0, float(item.get("score") or 0.0)))
                    )
                ),
                used_evidence_ids=[
                    ref for ref in item.get("evidence_refs") or [] if ref in evidence_ids
                ]
                or evidence_ids[:3],
                reason="沿用故障树的确定性证据排序，未增加新的故障假设。",
            )
            for item in candidates
            if item.get("cause_id")
        ],
        summary="AI 推理不可用，当前沿用故障树候选原因排序。",
        limitations=[limitation],
        next_verification_action=(str(actions[0].get("text")) if actions else None),
        conflict=bool(state.get("evidence_conflict")),
    )


def _validate_reasoning(
    raw_content: str,
    state: dict[str, Any],
    allowed_evidence: list[dict[str, str]],
) -> AIReasoningResult:
    result = AIReasoningResult.model_validate_json(raw_content)
    expected_error = state.get("error_type")
    if result.error_type != expected_error:
        raise ValueError("AI reasoning cannot change the deterministic error_type")
    candidates = {
        str(item.get("cause_id")): str(item.get("name"))
        for item in state.get("fault_tree_candidates") or []
        if item.get("cause_id")
    }
    cause_ids = [item.cause_id for item in result.ranked_causes]
    if len(cause_ids) != len(set(cause_ids)) or not set(cause_ids).issubset(candidates):
        raise ValueError("AI reasoning introduced an unknown or duplicate cause")
    allowed = {item["id"] for item in allowed_evidence}
    if any(
        item not in allowed
        for cause in result.ranked_causes
        for item in cause.used_evidence_ids
    ):
        raise ValueError("AI reasoning cited evidence outside the allowlist")
    allowed_actions = {
        str(item.get("text"))
        for item in state.get("allowed_verification_actions") or []
        if item.get("text")
    }
    if (
        result.next_verification_action
        and result.next_verification_action not in allowed_actions
    ):
        raise ValueError("AI reasoning proposed an action outside the allowlist")
    if result.conflict and any(
        item.support_level == "high" for item in result.ranked_causes
    ):
        raise ValueError("conflicting evidence cannot support a high ranking")
    if result.conclusion == "unknown" and result.ranked_causes:
        raise ValueError("unknown reasoning cannot contain ranked causes")
    if result.conclusion == "ranked" and not result.ranked_causes:
        raise ValueError("ranked reasoning requires at least one candidate")
    normalized = [
        cause.model_copy(update={"cause": candidates[cause.cause_id]})
        for cause in result.ranked_causes
    ]
    support_rank = {"high": 3, "medium": 2, "low": 1, "unknown": 0}
    normalized.sort(key=lambda item: (-support_rank[item.support_level], item.cause_id))
    return result.model_copy(update={"ranked_causes": normalized})


def _reasoning_prompt(
    state: dict[str, Any],
) -> tuple[str, str, str, list[dict[str, str]]]:
    evidence = build_evidence_registry(state)
    payload = {
        "prompt_version": REASONING_PROMPT_VERSION,
        "error_type": state.get("error_type"),
        "device_status": state.get("device_status"),
        "experiment_context": state.get("experiment_context"),
        "candidate_causes": state.get("fault_tree_candidates") or [],
        "evidence_registry": evidence,
        "knowledge_constraints": state.get("knowledge_constraints") or {},
        "allowed_verification_actions": state.get("allowed_verification_actions") or [],
        "output_json_schema": AIReasoningResult.model_json_schema(),
    }
    user_prompt = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    prompt_hash = hashlib.sha256(
        f"{REASONING_SYSTEM_PROMPT}\n{user_prompt}".encode()
    ).hexdigest()
    return REASONING_SYSTEM_PROMPT, user_prompt, prompt_hash, evidence


def _configured_clients(
    settings: Settings,
    ai_client: AIClient | None,
    ai_clients: list[tuple[str, AIClient]] | None,
) -> list[tuple[str, AIClient]]:
    if ai_clients is not None:
        return [(route, client) for route, client in ai_clients if client.configured]
    if ai_client is not None:
        return [(ai_client.provider, ai_client)] if ai_client.configured else []
    client = build_ai_client(settings)
    return [(client.provider, client)] if client.configured else []


def reason_about_causes(
    db: Session,
    diagnosis: DiagnosisResult,
    state: dict[str, Any],
    settings: Settings,
    *,
    workflow_run_id: str,
    call_stage: str = "reasoning",
    ai_client: AIClient | None = None,
    ai_clients: list[tuple[str, AIClient]] | None = None,
) -> tuple[AIReasoningResult, str]:
    """Rank only fault-tree candidates; return a deterministic fallback on any failure."""

    existing = db.scalar(
        select(AICallRecord).where(
            AICallRecord.workflow_run_id == workflow_run_id,
            AICallRecord.call_stage == call_stage,
        )
    )
    if existing and existing.output_json:
        return (
            AIReasoningResult.model_validate(existing.output_json),
            "ai" if existing.status == "succeeded" else "deterministic_fallback",
        )
    if not state.get("fault_tree_candidates"):
        return _fallback_reasoning(state, limitation="故障树没有可排序的候选原因。"), (
            "deterministic_fallback"
        )
    clients = _configured_clients(settings, ai_client, ai_clients) if settings.ai_enabled else []
    if not clients:
        return _fallback_reasoning(state, limitation="AI 推理未启用或 Provider 不可用。"), (
            "deterministic_fallback"
        )

    system_prompt, user_prompt, prompt_hash, evidence = _reasoning_prompt(state)
    started = time.monotonic()
    result: AIReasoningResult | None = None
    completion = None
    used_route = None
    used_client = None
    error: Exception | None = None
    attempts = 0
    for route, client in clients:
        attempts += 1
        try:
            candidate = client.complete_json(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
            )
            result = _validate_reasoning(candidate.content, state, evidence)
            completion = candidate
            used_route = route
            used_client = client
            break
        except Exception as exc:  # Provider and schema failures share one safe fallback.
            error = exc
    mode = "ai" if result is not None else "deterministic_fallback"
    if result is None:
        result = _fallback_reasoning(
            state,
            limitation="AI 推理失败或输出越界，已沿用故障树排序。",
        )
    duration_ms = int((time.monotonic() - started) * 1000)
    record = AICallRecord(
        diagnosis_result_id=diagnosis.id,
        workflow_run_id=workflow_run_id,
        call_stage=call_stage,
        provider=used_client.provider if used_client else clients[0][1].provider,
        model=used_client.model if used_client else clients[0][1].model,
        transport=settings.ai_transport,
        prompt_version=REASONING_PROMPT_VERSION,
        prompt_hash=prompt_hash,
        status="succeeded" if mode == "ai" else "failed",
        attempt_count=attempts,
        duration_ms=duration_ms,
        input_snapshot={
            "error_type": state.get("error_type"),
            "candidate_causes": state.get("fault_tree_candidates") or [],
            "evidence_registry": evidence,
            "allowed_verification_actions": state.get("allowed_verification_actions") or [],
        },
        output_json=result.model_dump(mode="json"),
        knowledge_references=[],
        input_tokens=completion.input_tokens if completion else None,
        output_tokens=completion.output_tokens if completion else None,
        trigger_reason="EVIDENCE_CAUSE_RANKING",
        cache_status="miss",
        route=used_route,
        route_path=used_route or "deterministic_fallback",
        latency_ms=duration_ms,
        validation_status="passed" if mode == "ai" else "fallback",
        fallback_reason=type(error).__name__ if error else None,
        error_code="AI_REASONING_FAILED" if error else None,
        error_message=type(error).__name__ if error else None,
        is_test_data=diagnosis.is_test_data,
    )
    db.add(record)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        replay = db.scalar(
            select(AICallRecord).where(
                AICallRecord.workflow_run_id == workflow_run_id,
                AICallRecord.call_stage == call_stage,
            )
        )
        if replay and replay.output_json:
            return (
                AIReasoningResult.model_validate(replay.output_json),
                "ai" if replay.status == "succeeded" else "deterministic_fallback",
            )
        raise
    return result, mode
