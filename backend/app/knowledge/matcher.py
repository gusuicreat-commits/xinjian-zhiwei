from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

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


def _rank_knowledge_cases(
    rows: Iterable[Any],
    diagnosis: DiagnosisResult,
    guidance: list[GuidanceHistory],
    *,
    limit: int = 5,
) -> list[MatchedKnowledgeCase]:
    error_types = {
        str(item.get("error_type")) for item in diagnosis.matched_rules if item.get("error_type")
    }
    if not error_types:
        return []
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
    for case in rows:
        if case.error_type not in error_types:
            continue
        matched_on = ["error_type"]
        score = 0.6
        case_experiment = case.experiment_type.lower()
        if case_experiment in experiments:
            score += 0.25
            matched_on.append("experiment_type")
        elif experiments:
            continue
        case_tokens = _tokens(case.symptom)
        for item in case.evidence:
            case_tokens.update(_tokens(item.get("fact")))
            case_tokens.update(_tokens(item.get("description")))
        if case_tokens & observed_tokens:
            score += 0.15
            matched_on.append("evidence")
        ranked.append(
            MatchedKnowledgeCase(
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
            )
        )
    ranked.sort(key=lambda item: (-item.match_score, item.case_id))
    return ranked[:limit]


def match_knowledge_case_definitions(
    diagnosis: DiagnosisResult,
    guidance: list[GuidanceHistory],
    cases: Iterable[Any],
    *,
    limit: int = 5,
) -> list[MatchedKnowledgeCase]:
    """Match reviewed package cases without copying them into the legacy global table."""

    approved = (
        case
        for case in cases
        if case.review_status == "approved"
        and case.root_cause_status == "confirmed"
        and case.facts_locked
        and case.quality_check_passed
        and (not case.is_test_data or diagnosis.is_test_data)
    )
    return _rank_knowledge_cases(approved, diagnosis, guidance, limit=limit)


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
        )
    )
    return _rank_knowledge_cases(rows, diagnosis, guidance, limit=limit)
