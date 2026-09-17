"""Server-owned explanation fields; no semantic judge or hardware inference."""

from app.ai.context_sanitizer import sanitize_text
from app.ai.schemas import AIDiagnosisInput

OUTPUT_CONTRACT_VERSION = "explanation-boundary-v2"


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
    summary = (
        "规则检测到异常；下列原因仅为待验证候选，不能据此确认硬件根因。"
        if payload.rule_matches
        else "未命中异常规则不单独证明实验正常，请以显式正常状态及其证据为准。"
    )
    errors = list(
        dict.fromkeys(
            sanitize_text(item["error_type"], max_chars=100)
            for item in payload.rule_matches
            if item.get("error_type")
        )
    )[:5]
    if errors:
        summary = "本次规则报告：" + "、".join(errors) + "。" + summary
    if payload.workflow_state.get("reasoning_status") == "unknown":
        summary += "当前推理结果为 unknown，尚不能给出有证据支持的原因排序。"
    limitations = ["候选排序不等于根因确认；实际接线、硬件状态和教学验收需要独立核验。"]
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
