from __future__ import annotations

import re
from collections.abc import Iterable
from copy import deepcopy
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.knowledge.applicability import context_from_diagnosis, evaluate_case_applicability
from app.models.diagnosis_result import DiagnosisResult
from app.models.guidance_history import GuidanceHistory
from app.models.knowledge import KnowledgeCase
from app.schemas.knowledge_case import MatchedKnowledgeCase


def _tokens(value: Any) -> set[str]:
    return {
        item for item in re.split(r"[^a-z0-9_\u4e00-\u9fff]+", str(value or "").lower()) if item
    }


def _experiment_candidates(diagnosis: DiagnosisResult) -> set[str]:
    context = diagnosis.context_snapshot or {}
    template = context.get("experiment_template") or {}
    candidates = {
        str(item) for item in (diagnosis.experiment_id, template.get("template_id")) if item
    }
    candidates.update(
        str(item.get("sensor_type"))
        for item in context.get("readings", [])
        if item.get("sensor_type")
    )
    return {item.lower() for item in candidates}


def match_case_candidates(
    rows: Iterable[Any],
    diagnosis: DiagnosisResult,
    guidance: list[GuidanceHistory],
    *,
    limit: int = 5,
) -> tuple[list[MatchedKnowledgeCase], list[dict[str, Any]]]:
    """Shared pure eligibility/ranking path for runtime and offline previews.

    The trace is internal: callers must not expose counts or identifiers from
    unauthorized collections. It never contains case text or private review data.
    """
    error_types = {
        str(item.get("error_type")) for item in diagnosis.matched_rules if item.get("error_type")
    }
    context = context_from_diagnosis(diagnosis, guidance)
    experiments = _experiment_candidates(diagnosis)
    observed_tokens = set().union(
        *(
            _tokens(value)
            for value in [
                *error_types,
                *(item.get("summary") for item in diagnosis.matched_rules),
                *(
                    evidence.get("fact")
                    for item in diagnosis.matched_rules
                    for evidence in item.get("evidence", [])
                ),
                *(cause.get("title") for item in guidance for cause in item.ranked_causes),
            ]
        )
    )
    ranked: list[MatchedKnowledgeCase] = []
    trace = []
    for case in rows:
        entry = {"case_id": case.id, "status": "omitted", "reason": "", "checks": []}
        trace.append(entry)
        gates = (
            (case.review_status == "approved", "review_not_approved"),
            (case.root_cause_status == "confirmed", "root_cause_not_confirmed"),
            (case.facts_locked is True, "facts_not_locked"),
            (case.quality_check_passed is True, "quality_not_passed"),
            (not case.is_test_data or diagnosis.is_test_data, "test_scope_mismatch"),
        )
        failed_gate = next((reason for passed, reason in gates if not passed), None)
        if failed_gate:
            entry["reason"] = failed_gate
            continue
        if case.error_type not in error_types:
            entry["reason"] = "error_type_mismatch"
            continue
        matched_on = ["error_type"]
        score = 0.6
        case_experiment = case.experiment_type.lower()
        if case_experiment in experiments:
            score += 0.25
            matched_on.append("experiment_type")
        elif experiments:
            entry["reason"] = "experiment_mismatch"
            continue
        applicability = evaluate_case_applicability(case.solution_record, context)
        entry["checks"] = [
            {"field": check.field, "status": check.status} for check in applicability.checks
        ]
        if applicability.projection is None:
            entry["reason"] = applicability.reason
            continue
        case_tokens = _tokens(case.symptom)
        for item in case.evidence:
            case_tokens.update(_tokens(item.get("fact")))
            case_tokens.update(_tokens(item.get("description")))
        if case_tokens & observed_tokens:
            score += 0.15
            matched_on.append("evidence")
        matched = MatchedKnowledgeCase(
                case_id=case.id,
                experiment_type=case.experiment_type,
                error_type=case.error_type,
                symptom=case.symptom,
                normal_state=case.normal_state,
                evidence=case.evidence,
                possible_causes=case.possible_causes,
                solution_steps=case.solution_steps,
                teacher_notes=case.teacher_notes,
                root_cause_value=case.root_cause_value,
                root_cause_status=case.root_cause_status,
                source_ref=case.source_ref,
                version=case.version,
                match_score=min(score, 1.0),
                matched_on=matched_on,
                is_test_data=case.is_test_data,
                applicability=applicability.projection,
        )
        matched._sensitive_sources = (deepcopy({
            "solution_record": case.solution_record,
            "facts": case.facts,
            # Review identity is not diagnosis evidence. Mark these narrowly,
            # before projection, so repetitions in prose are also removed.
            "secret": [
                value for value in (
                    getattr(case, "confirmed_by", None),
                    (case.solution_record.get("confirmation_material") or {}).get("confirmed_by"),
                    (case.solution_record.get("confirmation_material") or {}).get(
                        "recovery_diagnosis_id"
                    ),
                ) if isinstance(value, str) and value
            ],
        }),)
        ranked.append(matched)
        entry["reason"] = "top_k_omitted"
    ranked.sort(key=lambda item: (-item.match_score, item.case_id))
    selected = ranked[:max(limit, 0)]
    selected_ids = {item.case_id for item in selected}
    for entry in trace:
        if entry["reason"] == "top_k_omitted" and entry["case_id"] in selected_ids:
            entry.update(status="selected", reason="eligible")
    return selected, trace


def _rank_knowledge_cases(
    rows: Iterable[Any],
    diagnosis: DiagnosisResult,
    guidance: list[GuidanceHistory],
    *,
    limit: int = 5,
) -> list[MatchedKnowledgeCase]:
    """Compatibility wrapper; all runtime callers use the shared eligibility path."""
    return match_case_candidates(rows, diagnosis, guidance, limit=limit)[0]


def match_knowledge_case_definitions(
    diagnosis: DiagnosisResult,
    guidance: list[GuidanceHistory],
    cases: Iterable[Any],
    *,
    limit: int = 5,
) -> list[MatchedKnowledgeCase]:
    """Match reviewed package cases without copying them into the legacy global table."""

    return _rank_knowledge_cases(cases, diagnosis, guidance, limit=limit)


def match_knowledge_cases(
    db: Session,
    diagnosis: DiagnosisResult,
    guidance: list[GuidanceHistory],
    *,
    limit: int = 5,
) -> list[MatchedKnowledgeCase]:
    """Match approved cases by explicit fields only; no embedding or semantic search."""

    error_types = {
        str(item.get("error_type")) for item in diagnosis.matched_rules if item.get("error_type")
    }
    if not error_types:
        return []
    rows = list(
        db.scalars(
            select(KnowledgeCase)
            .where(
                KnowledgeCase.review_status == "approved",
                KnowledgeCase.root_cause_status == "confirmed",
                KnowledgeCase.facts_locked.is_(True),
                KnowledgeCase.quality_check_passed.is_(True),
                KnowledgeCase.error_type.in_(sorted(error_types)),
                or_(KnowledgeCase.is_test_data.is_(False), diagnosis.is_test_data),
            )
            .order_by(KnowledgeCase.id)
            .with_for_update(read=True)
            .execution_options(populate_existing=True)
        )
    )
    return _rank_knowledge_cases(rows, diagnosis, guidance, limit=limit)
