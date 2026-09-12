"""Server-owned explanation fields; no semantic judge or hardware inference."""

from app.ai.schemas import AIDiagnosisInput

OUTPUT_CONTRACT_VERSION = "explanation-boundary-v1"


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
    limitations = ["候选排序不等于根因确认；实际接线、硬件状态和教学验收需要独立核验。"]
    if payload.is_test_data:
        limitations.append("当前使用测试数据，不代表真实硬件或教师验证结果。")
    return {
        "version": OUTPUT_CONTRACT_VERSION,
        "allowed_steps": steps,
        "summary": summary,
        "limitations": limitations,
    }
