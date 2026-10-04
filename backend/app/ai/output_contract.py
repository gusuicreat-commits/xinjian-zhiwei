"""Server-owned explanation fields; no semantic judge or hardware inference."""

import json

from app.ai.context_sanitizer import sanitize_text
from app.ai.schemas import AIDiagnosisInput

OUTPUT_CONTRACT_VERSION = "explanation-boundary-v6"
REASONING_PROJECTION_VERSION = "reasoning-facts-v2"
SUPPORT_LEVELS = ("unknown", "low", "medium", "high")


def allowed_explanation_causes(payload: AIDiagnosisInput) -> list[dict[str, str]]:
    """One allowlist for generation, validation and frozen delivery contracts.

    Presence matters: an explicit empty result must never revive fault-tree
    candidates. The name-only explanation format cannot distinguish collisions.
    """
    state = payload.workflow_state
    legacy = "reasoning_status" not in state and "reasoned_causes" not in state
    if state.get("reasoning_status") == "unknown":
        return []
    rows = (
        [item for guidance in payload.fault_tree_guidance
         for item in guidance.get("ranked_causes", [])]
        if legacy else state.get("reasoned_causes") or []
    )
    allowed, identities, ambiguous = {}, {}, set()
    for item in rows:
        if not isinstance(item, dict):
            continue
        name = item.get("title" if legacy else "cause")
        if not isinstance(name, str) or not name:
            continue
        identity = item.get("cause_id")
        support = "high" if legacy else item.get("support_level") or "unknown"
        if support not in SUPPORT_LEVELS:
            ambiguous.add(name)
            continue
        if name in identities and identities[name] != identity:
            ambiguous.add(name)
        identities[name] = identity
        # Duplicate names with the same identity can only narrow support.
        previous = allowed.get(name, support)
        allowed[name] = min((previous, support), key=SUPPORT_LEVELS.index)
    return [{"cause": name, "max_support_level": support}
            for name, support in allowed.items() if name not in ambiguous]


def validate_explanation_causes(causes, contract: dict) -> None:
    """Also used when reading stored outputs; the frozen contract is required."""
    allowed = {item["cause"]: item["max_support_level"] for item in contract["allowed_causes"]}
    if any(item.cause not in allowed for item in causes):
        raise ValueError("AI explanation introduced a cause outside constrained reasoning")
    if any(SUPPORT_LEVELS.index(item.support_level) > SUPPORT_LEVELS.index(allowed[item.cause])
           for item in causes):
        raise ValueError("AI explanation increased a constrained support level")


def project_reasoning(reasoning: dict, *, allowed_actions=(), evidence_registry=()) -> dict:
    """Detach current facts from untrusted prose, including old checkpoints.

    Callers supply previously validated candidates/status. This projection does
    not infer a physical root cause or turn a suggested check into an absence.
    """
    from copy import deepcopy

    result = deepcopy({key: value for key, value in reasoning.items() if key in {
        "error_type", "conclusion", "status", "mode", "ranked_causes",
        "missing_evidence", "next_verification_action", "conflict",
    }})
    result["ranked_causes"] = [
        {**{key: value for key, value in (
            item.model_dump() if hasattr(item, "model_dump") else item
        ).items() if key not in {"reason", "rationale", "evidence", "confidence"}},
         "reason": "引用仅表示与候选关联的来源记录，不证明支持方向或实际根因。"}
        for item in result.get("ranked_causes") or []
    ]
    status = result.get("status", result.get("conclusion"))
    ranked = result.get("ranked_causes") or []
    if "status" in result or "conclusion" not in result:
        result["status"] = "ranked" if status == "ranked" and ranked else "unknown"
    result["summary"] = (
        "现有证据不足以形成候选原因排序，根因尚未确认。"
        if status != "ranked" or not ranked
        else "当前仅形成待验证的候选原因排序，不能据此确认根因。"
    )
    if result.get("conflict"):
        result["summary"] += "当前存在证据冲突，需要先核对来源。"
    texts = {item.get("text") for item in allowed_actions if isinstance(item, dict)}
    action = result.get("next_verification_action")
    action = action if isinstance(action, str) and action and action in texts else None
    result["next_verification_action"] = action
    result["missing_evidence"] = []
    result["verification_requests"] = (
        [{"text": action, "source": "rules", "status": "unverified"}] if action else []
    )
    # Source attribution is not a verified configuration comparison.
    result["reported_evidence"] = [
        {key: sanitize_text(item.get(key), max_chars=None)
         for key in ("id", "fact", "source", "status")}
        for item in evidence_registry if isinstance(item, dict) and item.get("id")
    ]
    result["projection_version"] = REASONING_PROJECTION_VERSION
    return result


def diagnosis_summary(rule_matches: list[dict], reasoning_status: str | None = None) -> str:
    summary = (
        "规则检测到异常；下列原因仅为待验证候选，不能据此确认硬件根因。"
        if rule_matches
        else "未命中异常规则不单独证明实验正常，请以显式正常状态及其证据为准。"
    )
    errors = list(dict.fromkeys(
        sanitize_text(item["error_type"], max_chars=100)
        for item in rule_matches if item.get("error_type")
    ))[:5]
    if errors:
        summary = "本次规则报告：" + "、".join(errors) + "。" + summary
    if reasoning_status == "unknown":
        summary += "当前推理结果为 unknown，尚不能给出有证据支持的原因排序。"
    return summary


def explanation_contract(payload: AIDiagnosisInput) -> dict:
    # An explicitly empty workflow allowlist must stay empty. Legacy callers
    # may only select persisted guidance hints, not arbitrary knowledge prose.
    if "allowed_verification_actions" in payload.workflow_state:
        actions = payload.workflow_state.get("allowed_verification_actions") or []
    else:
        actions = [hint for item in payload.fault_tree_guidance for hint in item.get("hints", [])]
    steps = list(
        dict.fromkeys(
            item["text"] for item in actions if isinstance(item, dict) and item.get("text")
        )
    )
    summary = diagnosis_summary(
        payload.rule_matches, payload.workflow_state.get("reasoning_status")
    )
    limitations = ["候选排序不等于根因确认；实际接线、硬件状态和教学验收需要独立核验。"]
    for reference in payload.knowledge:
        try:
            case = json.loads(reference.content)
        except (ValueError, TypeError):
            continue
        if isinstance(case, dict) and (case.get("applicability") or {}).get(
            "condition_status"
        ) == "text_only":
            limitations.append("参考案例的适用条件尚未自动核验，使用时必须同时核对所列限制。")
            break
    if payload.workflow_state.get("evidence_conflict"):
        limitations.append("当前流程标记存在证据冲突，需要先核对冲突来源。")
    if not steps:
        limitations.append("当前没有适用的核验指导；可请求教师帮助核对所需材料。")
    if payload.is_test_data:
        limitations.append("当前使用测试数据，不代表真实硬件或教师验证结果。")
    return {
        "version": OUTPUT_CONTRACT_VERSION,
        "allowed_causes": allowed_explanation_causes(payload),
        "allowed_steps": steps,
        "summary": summary,
        "limitations": limitations,
    }


def project_explanation_state(state: dict) -> dict:
    """Current delivery boundary, also used for old graph/checkpoint inputs."""
    from copy import deepcopy

    result = deepcopy(state)
    projected = project_reasoning({
        "status": state.get("reasoning_status"),
        "ranked_causes": state.get("reasoned_causes") or [],
        "next_verification_action": state.get("next_verification_action"),
        "conflict": state.get("evidence_conflict"),
    }, allowed_actions=state.get("allowed_verification_actions") or [])
    for key in ("reasoned_causes", "possible_causes"):
        if key in state:
            result[key] = project_reasoning({"ranked_causes": state[key] or []})["ranked_causes"]
    if "reasoning_summary" in state:
        result["reasoning_summary"] = projected["summary"]
    if "missing_evidence" in state:
        result["missing_evidence"] = []
    if "next_verification_action" in state:
        result["next_verification_action"] = projected["next_verification_action"]
    return result
