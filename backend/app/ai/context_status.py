"""Shared, source-free explanations of context preparation failures."""

CONTEXT_NOTICES = {
    "INPUT_TOKEN_LIMIT": "必需上下文无法完整放入预算，当前保留确定性结果。",
    "KNOWLEDGE_CONTEXT_BUDGET_EXCEEDED": (
        "匹配案例无法完整放入本次上下文预算，当前保留确定性结果。"
    ),
    "KNOWLEDGE_NOT_READY": (
        "尚无匹配且已审核的结构化知识案例，当前仅展示确定性诊断。"
    ),
}


def context_skip_code(manifest: dict, *, require_knowledge: bool) -> str | None:
    if manifest.get("required_complete") is False:
        return "INPUT_TOKEN_LIMIT"
    if require_knowledge and not (manifest.get("selected_ids") or {}).get("case_ids"):
        if (manifest.get("omission_counts") or {}).get("budget_omitted", 0):
            return "KNOWLEDGE_CONTEXT_BUDGET_EXCEEDED"
        return "KNOWLEDGE_NOT_READY"
    return None


def stage_context_skip_code(
    stage: str, manifest: dict, *, require_knowledge: bool
) -> str | None:
    """Apply the runtime stage contract, independently of source/auth checks.

    Reasoning may assess the current evidence without an approved historical
    case. Explanations obey the configured knowledge requirement. Feedback
    suffixes identify invocations, not a different preparation policy.
    """
    stage = stage.partition(":")[0]
    if stage not in {"reasoning", "explanation"}:
        raise ValueError("unsupported context stage")
    return context_skip_code(
        manifest, require_knowledge=stage == "explanation" and require_knowledge
    )


def context_skip_notice(error_code: str | None, manifest: dict) -> str | None:
    # Correct old misclassified notices on read only. Authorization/source
    # checks still take precedence at the delivery boundary.
    if error_code == "KNOWLEDGE_NOT_READY":
        error_code = context_skip_code(manifest, require_knowledge=True) or error_code
    return CONTEXT_NOTICES.get(error_code)
