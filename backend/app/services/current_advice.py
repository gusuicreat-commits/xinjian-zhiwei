"""Read-only delivery projections; never rewrite a recorded workflow or call a model."""

from copy import deepcopy

from sqlalchemy import select

from app.ai.context_contract import current_context_policy
from app.diagnosis.lightweight_schemas import DiagnosisCore
from app.models import AICallRecord, DiagnosisResult
from app.services.lightweight_diagnosis import (
    build_diagnosis_core,
    render_deterministic_explanation,
)

LEGACY_CONTEXT_NOTICE = "原AI增强未通过当前适用条件检查；当前显示确定性诊断，历史记录保留。"
LEGACY_CONTEXT_STATUS = "legacy_enhancement_not_revalidated"


def _policy(record):
    if record is None or record.status != "succeeded" or not record.output_json:
        return False
    try:
        return current_context_policy(record.input_snapshot)
    except (AttributeError, TypeError):
        return False


def _inspection(db, workflow, advice, *, interrupt=False):
    """Bind the active explanation and reasoning pair, not any later successful call.

    Resolved feedback need not call the model again: its result can still derive
    from the previous explanation stage. Only the call ID frozen alongside the
    displayed content is a binding; the diagnosis's mutable latest call is not.
    """
    diagnosis = db.get(DiagnosisResult, workflow.diagnosis_result_id)
    final = advice if not interrupt else {}
    request = advice if interrupt else {}
    mode = (final.get("ai_reasoning") or {}).get("mode")
    uses_reasoning = mode == "ai"
    uses_explanation = bool(request.get("ai_result")) or bool(
        final and final.get("provenance") != "rules_and_reviewed_knowledge"
    )
    if diagnosis is None:
        return None, uses_reasoning or uses_explanation, True
    records = list(db.scalars(select(AICallRecord).where(
        AICallRecord.workflow_run_id == workflow.id,
        AICallRecord.diagnosis_result_id == diagnosis.id,
    )))
    by_id = {record.id: record for record in records}
    delivery = advice.get("context_delivery")
    anchor_id = delivery.get("explanation_call_id") if isinstance(delivery, dict) else None
    if not isinstance(anchor_id, str):
        anchor_id = None
    anchor = by_id.get(anchor_id)
    stage = anchor.call_stage if anchor else ""
    valid_stage = stage == "explanation" or (
        stage.startswith("explanation:feedback:")
        and bool(stage.removeprefix("explanation:feedback:"))
    )
    if not valid_stage:
        anchor = None
    paired = next((
        record for record in records
        if anchor and record.call_stage == "reasoning" + stage[len("explanation"):]
    ), None)
    # Interrupt snapshots do not contain reasoning_mode. Their next-action text
    # may derive from a successful reasoning call even if explanation was skipped.
    if request and not final:
        uses_reasoning = bool(paired and paired.status == "succeeded") or (
            anchor is None and any(
                record.status == "succeeded" and record.call_stage.startswith("reasoning")
                for record in records
            )
        )
    used = uses_reasoning or uses_explanation
    invalid = bool(used and (
        anchor is None
        or (uses_explanation and not _policy(anchor))
        or (uses_reasoning and not _policy(paired))
    ))
    return diagnosis, used, invalid


def workflow_context_status(db, workflow):
    """Audit label only; this does not authorize a historical result for current use."""
    inspected = [
        _inspection(db, workflow, value, interrupt=interrupt)
        for value, interrupt in ((workflow.final_result, False), (workflow.review_request, True))
        if value is not None
    ]
    used = any(used for _, used, _ in inspected)
    invalid = any(invalid for _, _, invalid in inspected)
    return "legacy_or_unverified_policy" if invalid else (
        "current_policy" if used else "deterministic_only"
    )


def _deterministic(diagnosis, workflow):
    if diagnosis is None:
        return None
    try:
        core = DiagnosisCore.model_validate(diagnosis.deterministic_core)
    except (ValueError, TypeError):
        core = build_diagnosis_core(diagnosis, list(diagnosis.guidance_history))
    result = render_deterministic_explanation(core).model_dump(mode="json")
    result["limitations"] = [*result["limitations"], LEGACY_CONTEXT_NOTICE]
    result.update(
        context_policy_status=LEGACY_CONTEXT_STATUS,
        rules_preserved=True,
        rule_hits=deepcopy(diagnosis.matched_rules),
        error_type=core.primary_error_code,
        evidence_score=workflow.evidence_score,
        hint_level=workflow.guidance_level or core.hint_level,
        guidance_level=workflow.guidance_level or core.hint_level,
        need_teacher_help=bool(workflow.needs_teacher),
        knowledge_references=[],
    )
    return result


def project_current_advice(db, workflow):
    """Return detached result/interrupt dictionaries; do not persist this view."""
    final = deepcopy(workflow.final_result)
    request = deepcopy(workflow.review_request)
    if final is not None:
        diagnosis, _, invalid = _inspection(db, workflow, final)
        if invalid:
            previous = final
            final = _deterministic(diagnosis, workflow)
            if final is not None:
                final["student_feedback"] = deepcopy(previous.get("student_feedback"))
                final["teacher_reviewed"] = False
                final["historical_teacher_reviewed"] = bool(previous.get("teacher_reviewed"))
                if previous.get("teacher_reviewed"):
                    final["limitations"].append("原教师编辑保留为历史，不视为对当前回退说明的新审核。")
    if request is not None:
        diagnosis, _, invalid = _inspection(db, workflow, request, interrupt=True)
        if invalid:
            request.update(
                ai_result=None, deterministic_result=_deterministic(diagnosis, workflow),
                next_verification_action=None, retrieved_chunks=[],
                context_policy_status=LEGACY_CONTEXT_STATUS,
            )
    return final, request
