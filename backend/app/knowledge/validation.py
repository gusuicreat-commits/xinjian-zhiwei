from __future__ import annotations

import json
from typing import Any

from app.ai.context_sanitizer import sanitize_text
from app.ai.schemas import AIKnowledgeReference


def _safe_case_payload(reference: AIKnowledgeReference) -> dict[str, Any] | None:
    try:
        raw = json.loads(reference.content)
    except (TypeError, ValueError, json.JSONDecodeError):
        return None
    if not isinstance(raw, dict):
        return None
    return {
        "case_id": sanitize_text(raw.get("caseId") or reference.chunk_id, max_chars=100),
        "experiment_type": sanitize_text(raw.get("experimentType"), max_chars=100),
        "error_type": sanitize_text(raw.get("errorType"), max_chars=100),
        "symptom": sanitize_text(raw.get("symptom"), max_chars=500),
        "normal_state": raw.get("normalState") if isinstance(raw.get("normalState"), dict) else {},
        "evidence": raw.get("evidence") if isinstance(raw.get("evidence"), list) else [],
        "possible_causes": (
            raw.get("possibleCauses") if isinstance(raw.get("possibleCauses"), list) else []
        ),
        "solution_steps": (
            raw.get("solutionSteps") if isinstance(raw.get("solutionSteps"), list) else []
        ),
        "teacher_notes": sanitize_text(raw.get("teacherNotes"), max_chars=1000),
        "root_cause": raw.get("rootCause") if isinstance(raw.get("rootCause"), dict) else {},
        "source_id": sanitize_text(reference.source_key, max_chars=200),
    }


def build_reasoning_knowledge_constraints(
    experiment_context: dict[str, Any] | None,
    references: list[AIKnowledgeReference],
) -> dict[str, Any]:
    """Project trusted structured knowledge into a bounded pre-reasoning contract."""

    cases = [item for ref in references if (item := _safe_case_payload(ref)) is not None]
    return {
        "experiment_definition": experiment_context or {},
        "normal_conditions": [
            {"case_id": item["case_id"], "normal_state": item["normal_state"]}
            for item in cases
            if item["normal_state"]
        ],
        "standard_fault_mappings": [
            {
                "case_id": item["case_id"],
                "error_type": item["error_type"],
                "possible_causes": item["possible_causes"],
                "confirmed_root_cause": item["root_cause"],
            }
            for item in cases
        ],
        "teacher_confirmed_cases": cases,
    }


def validate_reasoning_against_knowledge(state: dict[str, Any]) -> dict[str, Any]:
    """Deterministically validate AI reasoning after it has been produced.

    This is deliberately independent of the model. It validates identities and
    constraints rather than attempting another semantic diagnosis.
    """

    rule_errors = {
        str(item.get("error_type"))
        for item in state.get("rule_hits") or []
        if item.get("error_type")
    }
    error_type = state.get("error_type")
    candidate_ids = {
        str(item.get("cause_id"))
        for item in state.get("fault_tree_candidates") or []
        if item.get("cause_id")
    }
    reasoned = [item for item in state.get("reasoned_causes") or [] if isinstance(item, dict)]
    reasoned_ids = {str(item.get("cause_id")) for item in reasoned if item.get("cause_id")}
    evidence_ids = {
        str(item.get("id"))
        for item in state.get("evidence_registry") or []
        if item.get("id")
    }
    used_evidence_ids = {
        str(evidence_id)
        for item in reasoned
        for evidence_id in item.get("used_evidence_ids") or []
    }
    allowed_actions = {
        str(item.get("text"))
        for item in state.get("allowed_verification_actions") or []
        if item.get("text")
    }
    next_action = state.get("next_verification_action")
    constraints = state.get("knowledge_constraints") or {}
    cases = constraints.get("teacher_confirmed_cases") or []
    definition = constraints.get("experiment_definition") or {}
    template = definition.get("template") or {}
    experiment_types = {
        str(value)
        for value in (
            state.get("experiment_type"),
            definition.get("experiment_id"),
            template.get("template_id"),
        )
        if value
    }

    checks = {
        "error_type_preserved": not rule_errors or error_type in rule_errors,
        "cause_ids_in_fault_tree": reasoned_ids.issubset(candidate_ids),
        "evidence_ids_exist": used_evidence_ids.issubset(evidence_ids),
        "verification_action_allowed": not next_action or next_action in allowed_actions,
        "experiment_spec_consistent": not experiment_types
        or all(
            not item.get("experiment_type")
            or str(item.get("experiment_type")) in experiment_types
            for item in cases
            if isinstance(item, dict)
        ),
        "knowledge_error_type_consistent": all(
            not item.get("error_type") or item.get("error_type") == error_type
            for item in cases
            if isinstance(item, dict)
        ),
        "conflict_has_no_high_support": not state.get("evidence_conflict")
        or all(item.get("support_level") != "high" for item in reasoned),
    }
    messages = {
        "error_type_preserved": "AI 输出与规则确定的异常类型冲突。",
        "cause_ids_in_fault_tree": "AI 输出包含故障树候选集合之外的原因。",
        "evidence_ids_exist": "AI 输出引用了不存在的证据 ID。",
        "verification_action_allowed": "AI 输出包含未经规则或知识允许的验证动作。",
        "experiment_spec_consistent": "AI 使用的知识与当前实验定义不一致。",
        "knowledge_error_type_consistent": "匹配案例与规则异常类型不一致。",
        "conflict_has_no_high_support": "证据冲突时不能给出 high 支持等级。",
    }
    violations = [messages[name] for name, passed in checks.items() if not passed]
    return {
        "status": (
            "rejected"
            if violations
            else "validated"
            if cases
            else "validated_without_case"
        ),
        "checks": checks,
        "violations": violations,
        "case_ids": [
            item.get("case_id") for item in cases if isinstance(item, dict) and item.get("case_id")
        ],
        "reasoned_cause_ids": sorted(reasoned_ids),
        "note": (
            "推理结果已通过候选集合、证据 ID、规则结果与结构化知识约束校验。"
            if not violations
            else "推理结果未通过确定性知识校验，不能作为学生建议发布。"
        ),
    }
