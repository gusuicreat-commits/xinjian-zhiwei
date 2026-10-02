"""Server-owned explanation fields; no semantic judge or hardware inference."""

import json

from app.ai.context_sanitizer import sanitize_text
from app.ai.schemas import AIDiagnosisInput

OUTPUT_CONTRACT_VERSION = "explanation-boundary-v4"
REASONING_PROJECTION_VERSION = "reasoning-facts-v1"


def project_reasoning(reasoning: dict) -> dict:
    """Detach current facts from untrusted prose, including old checkpoints.

    Callers supply previously validated candidates/status. This projection does
    not infer a physical root cause or turn a suggested check into an absence.
    """
    from copy import deepcopy

    result = deepcopy(reasoning)
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
    result["verification_requests"] = [
        {"text": sanitize_text(item, max_chars=1000),
         "source": "model" if result.get("mode", "ai") == "ai" else "rules",
         "status": "unverified"}
        for item in result.get("missing_evidence") or []
        if isinstance(item, str) and item.strip()
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
    # These are model-originated requests, not verified absence or hardware facts.
    # Keep their specific information, explicitly quoted as pending review.
    requests = payload.workflow_state.get("missing_evidence") or []
    if isinstance(requests, list):
        for item in dict.fromkeys(
            text for text in requests if isinstance(text, str) and text.strip()
        ):
            if len(limitations) >= 12:
                break
            limitations.append(
                "推理提出的待核验项（未确认）：" + "「" + sanitize_text(item, max_chars=500) + "」"
            )
    if payload.is_test_data:
        limitations.append("当前使用测试数据，不代表真实硬件或教师验证结果。")
    return {
        "version": OUTPUT_CONTRACT_VERSION,
        "allowed_steps": steps,
        "summary": summary,
        "limitations": limitations,
    }
