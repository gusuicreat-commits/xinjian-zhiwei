from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from typing import Any

from sqlalchemy.orm import Session

from app.ai.clients import AIClient, build_ai_client
from app.core.config import Settings
from app.models.base import utc_now
from app.models.diagnosis_feedback import DiagnosisFeedback
from app.models.diagnosis_result import DiagnosisResult
from app.models.guidance_history import GuidanceHistory
from app.models.knowledge import KnowledgeCase, KnowledgeCaseDraft
from app.schemas.knowledge_case import AICasePolishFields

FACT_FIELDS = {
    "experimentType",
    "errorType",
    "normalState",
    "evidence",
    "possibleCauses",
    "solutionSteps",
}
ALLOWED_AI_FIELDS = {
    "title",
    "symptomDescription",
    "teachingNote",
    "solutionSummary",
    "sourceIds",
}
DEFINITE_CAUSAL_TERMS = ("根因是", "确定为", "导致了", "必然导致")
CASE_POLISH_PROMPT_VERSION = "knowledge-case-polish-v1"


class CaseDraftError(ValueError):
    pass


def _experiment_type(diagnosis: DiagnosisResult) -> str | None:
    context = diagnosis.context_snapshot or {}
    template = context.get("experiment_template") or {}
    readings = context.get("readings") or []
    return (
        diagnosis.experiment_id
        or template.get("template_id")
        or next((item.get("sensor_type") for item in readings if item.get("sensor_type")), None)
    )


def build_case_draft(
    db: Session,
    diagnosis: DiagnosisResult,
    feedback: DiagnosisFeedback,
    guidance: list[GuidanceHistory],
    *,
    commit: bool = True,
) -> KnowledgeCaseDraft:
    """Build a fact-only draft; this function never publishes a KnowledgeCase."""

    if feedback.diagnosis_result_id != diagnosis.id:
        raise CaseDraftError("feedback does not belong to the diagnosis")
    experiment_type = _experiment_type(diagnosis)
    error_type = next(
        (
            str(item.get("error_type"))
            for item in diagnosis.matched_rules
            if item.get("error_type")
        ),
        None,
    )
    if not experiment_type or not error_type:
        raise CaseDraftError("diagnosis lacks a verified experiment or error type")
    causes = list(
        dict.fromkeys(
            str(cause.get("title"))
            for item in guidance
            for cause in item.ranked_causes
            if cause.get("title")
        )
    )
    candidate_causes = list(
        {
            (
                str(cause.get("cause_id") or ""),
                str(cause.get("title") or ""),
            )
            for item in guidance
            for cause in item.ranked_causes
            if cause.get("cause_id") and cause.get("title")
        }
    )
    deterministic = diagnosis.deterministic_explanation or {}
    steps = [str(item) for item in deterministic.get("steps", []) if item]
    summaries = [
        str(item.get("summary")) for item in diagnosis.matched_rules if item.get("summary")
    ]
    context = diagnosis.context_snapshot or {}
    expected_behaviors = context.get("expected_behaviors") or []
    source_ids = list(
        dict.fromkeys(
            [feedback.id]
            + [
                str(item.get("rule_id"))
                for item in diagnosis.matched_rules
                if item.get("rule_id")
            ]
            + [
                str(ref)
                for item in diagnosis.evidence
                for ref in item.get("evidence_refs", [])
                if ref
            ]
        )
    )
    template_payload = {
        "experimentType": experiment_type,
        "errorType": error_type,
        "symptom": "；".join(summaries) or error_type,
        "normalState": {"expectedBehaviors": expected_behaviors},
        "evidence": diagnosis.evidence,
        "possibleCauses": causes,
        "solutionSteps": steps,
        "teacherNotes": None,
        "aiGeneratedFields": {},
        "reviewStatus": "pending",
    }
    checks = [
        {"check": "student_feedback_confirmed", "passed": feedback.action == "resolved"},
        {"check": "rule_error_type_present", "passed": bool(error_type)},
        {"check": "deterministic_evidence_present", "passed": bool(diagnosis.evidence)},
        {"check": "fault_tree_causes_present", "passed": bool(causes)},
        {
            "check": "root_cause_not_inferred_from_student_feedback",
            "passed": True,
        },
        {"check": "source_ids_present", "passed": bool(source_ids)},
    ]
    draft = KnowledgeCaseDraft(
        diagnosis_result_id=diagnosis.id,
        feedback_id=feedback.id,
        experiment_type=experiment_type,
        error_type=error_type,
        fact_snapshot={
            "diagnosis_result_id": diagnosis.id,
            "feedback_id": feedback.id,
            "feedback_action": feedback.action,
            "ruleset_version": diagnosis.ruleset_version,
            "rule_matches": diagnosis.matched_rules,
            "evidence": diagnosis.evidence,
            "fault_tree_versions": sorted(
                {item.fault_tree_version for item in guidance if item.fault_tree_version}
            ),
            "candidate_causes": [
                {"cause_id": cause_id, "title": title}
                for cause_id, title in sorted(candidate_causes)
            ],
        },
        template_payload=template_payload,
        quality_checks=checks,
        root_cause={
            "value": None,
            "status": "unknown",
            "confirmed_by": None,
        },
        solution_record={
            "student_reported_outcome": feedback.action,
            "student_note": feedback.note,
            "verified_steps": [],
        },
        source_ids=source_ids,
        allowed_ai_fields=sorted(ALLOWED_AI_FIELDS),
        facts_locked=True,
        status=("pending_review" if all(item["passed"] for item in checks) else "draft"),
        is_test_data=diagnosis.is_test_data,
    )
    db.add(draft)
    if commit:
        db.commit()
        db.refresh(draft)
    else:
        db.flush()
    return draft


def apply_ai_assisted_polish(
    db: Session,
    draft: KnowledgeCaseDraft,
    polished_payload: dict[str, Any],
) -> KnowledgeCaseDraft:
    """Accept wording improvements only when all fact-bearing fields are unchanged."""

    baseline = draft.template_payload or {}
    changed_fact_fields = [
        field
        for field in FACT_FIELDS
        if polished_payload.get(field) != baseline.get(field)
    ]
    if changed_fact_fields:
        raise CaseDraftError(
            "AI polish changed verified facts: " + ", ".join(sorted(changed_fact_fields))
        )
    allowed = {
        *FACT_FIELDS,
        "symptom",
        "teacherNotes",
        "aiGeneratedFields",
        "reviewStatus",
    }
    if set(polished_payload) - allowed:
        raise CaseDraftError("AI polish contains unsupported fields")
    merged = deepcopy(baseline)
    merged["symptom"] = str(polished_payload.get("symptom") or baseline.get("symptom") or "")
    merged["teacherNotes"] = polished_payload.get("teacherNotes")
    generated = polished_payload.get("aiGeneratedFields") or {}
    if not isinstance(generated, dict) or set(generated) - ALLOWED_AI_FIELDS:
        raise CaseDraftError("AI polish contains unsupported generated fields")
    if generated.get("sourceIds") != draft.source_ids:
        raise CaseDraftError("AI generated fields must preserve all source IDs")
    if (draft.root_cause or {}).get("status") != "confirmed" and any(
        term in str(value)
        for value in generated.values()
        if isinstance(value, str)
        for term in DEFINITE_CAUSAL_TERMS
    ):
        raise CaseDraftError("unconfirmed root cause cannot use definite causal wording")
    merged["aiGeneratedFields"] = generated
    merged["reviewStatus"] = "pending"
    draft.polished_payload = merged
    draft.quality_checks = [
        *(draft.quality_checks or []),
        {"check": "ai_preserved_verified_facts", "passed": True},
    ]
    draft.status = "quality_checked"
    db.commit()
    db.refresh(draft)
    return draft


def generate_ai_assisted_polish(
    db: Session,
    draft: KnowledgeCaseDraft,
    settings: Settings,
    *,
    ai_client: AIClient | None = None,
) -> KnowledgeCaseDraft:
    """Let AI fill expression-only fields and then enforce the fact boundary."""

    client = ai_client or build_ai_client(settings)
    if not settings.ai_enabled or not client.configured:
        raise CaseDraftError("AI case polishing is not configured")
    system_prompt = """你是实验案例文档整理助手，只能整理已锁定事实，不能创造知识。
只能输出 title、symptomDescription、teachingNote、solutionSummary、sourceIds。
sourceIds 必须原样保留。root_cause.status 不是 confirmed 时，禁止使用确定因果措辞。
材料不足时写“信息不足”，只输出 JSON。"""
    prompt_payload = {
        "prompt_version": CASE_POLISH_PROMPT_VERSION,
        "locked_facts": draft.fact_snapshot,
        "root_cause": draft.root_cause,
        "solution_record": draft.solution_record,
        "source_ids": draft.source_ids,
        "allowed_fields": draft.allowed_ai_fields,
        "output_schema": AICasePolishFields.model_json_schema(),
    }
    user_prompt = json.dumps(prompt_payload, ensure_ascii=False, separators=(",", ":"))
    prompt_hash = hashlib.sha256(
        f"{system_prompt}\n{user_prompt}".encode()
    ).hexdigest()
    try:
        completion = client.complete_json(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
        )
        generated = AICasePolishFields.model_validate_json(completion.content)
    except Exception as exc:
        raise CaseDraftError("AI case polish failed validation") from exc
    polished = deepcopy(draft.template_payload or {})
    polished["aiGeneratedFields"] = generated.model_dump(
        mode="json", by_alias=True
    )
    draft.ai_audit = {
        "provider": client.provider,
        "model": client.model,
        "prompt_version": CASE_POLISH_PROMPT_VERSION,
        "prompt_hash": prompt_hash,
        "input_tokens": completion.input_tokens,
        "output_tokens": completion.output_tokens,
        "validation_status": "passed",
    }
    return apply_ai_assisted_polish(db, draft, polished)


def submit_case_draft_for_review(
    db: Session, draft: KnowledgeCaseDraft
) -> KnowledgeCaseDraft:
    if not draft.quality_checks or not all(
        bool(item.get("passed")) for item in draft.quality_checks
    ):
        raise CaseDraftError("case draft failed quality checks")
    draft.status = "pending_review"
    db.commit()
    db.refresh(draft)
    return draft


def approve_case_draft(
    db: Session,
    draft: KnowledgeCaseDraft,
    *,
    case_id: str,
    reviewer_ref: str,
    confirmed_root_cause: str,
    final_solution_steps: list[str],
    confirmation_note: str,
) -> KnowledgeCase:
    if draft.status != "pending_review":
        raise CaseDraftError("case draft is not ready for teacher review")
    if db.get(KnowledgeCase, case_id) is not None:
        raise CaseDraftError("knowledge case id already exists")
    allowed_causes = {
        str(item)
        for item in (draft.template_payload or {}).get("possibleCauses", [])
        if item
    }
    allowed_causes.update(
        str(item.get("cause_id"))
        for item in (draft.fact_snapshot or {}).get("candidate_causes", [])
        if item.get("cause_id")
    )
    if confirmed_root_cause not in allowed_causes:
        raise CaseDraftError("confirmed root cause is outside the fault-tree candidates")
    if not final_solution_steps or any(not str(item).strip() for item in final_solution_steps):
        raise CaseDraftError("teacher-confirmed solution steps are required")
    if not draft.facts_locked or not draft.source_ids:
        raise CaseDraftError("case facts are not locked or traceable")
    payload = draft.polished_payload or draft.template_payload
    confirmed_at = utc_now()
    quality_checks = [
        *(draft.quality_checks or []),
        {"check": "teacher_confirmed_root_cause", "passed": True},
        {"check": "teacher_confirmed_solution", "passed": True},
        {"check": "facts_locked", "passed": True},
        {"check": "source_ids_traceable", "passed": True},
    ]
    if not all(bool(item.get("passed")) for item in quality_checks):
        raise CaseDraftError("case draft failed quality checks")
    root_cause = {
        "value": confirmed_root_cause,
        "status": "confirmed",
        "confirmed_by": reviewer_ref,
        "confirmed_at": confirmed_at.isoformat(),
    }
    solution_record = {
        "steps": [str(item).strip() for item in final_solution_steps],
        "outcome": "resolved",
        "confirmation_note": confirmation_note,
        "source_ids": draft.source_ids,
    }
    case = KnowledgeCase(
        id=case_id,
        experiment_type=draft.experiment_type,
        error_type=draft.error_type,
        symptom=str(payload.get("symptom") or draft.error_type),
        normal_state=payload.get("normalState") or {},
        evidence=payload.get("evidence") or [],
        possible_causes=payload.get("possibleCauses") or [],
        solution_steps=solution_record["steps"],
        teacher_notes=payload.get("teacherNotes"),
        facts=draft.fact_snapshot,
        root_cause_value=confirmed_root_cause,
        root_cause_status="confirmed",
        confirmed_by=reviewer_ref,
        confirmed_at=confirmed_at,
        solution_record=solution_record,
        ai_generated_fields=payload.get("aiGeneratedFields") or {},
        source_type="real_experiment",
        facts_locked=True,
        quality_check_passed=True,
        review_status="approved",
        source_ref=f"diagnosis-case-draft:{draft.id}",
        version="1",
        is_test_data=draft.is_test_data,
    )
    draft.status = "approved"
    draft.root_cause = root_cause
    draft.solution_record = solution_record
    draft.quality_checks = quality_checks
    draft.reviewer_ref = reviewer_ref
    draft.reviewed_at = utc_now()
    db.add(case)
    db.commit()
    db.refresh(case)
    return case
