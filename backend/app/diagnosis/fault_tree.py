from dataclasses import dataclass
from operator import eq, ge, gt, le, lt
from typing import Any, Callable, Optional

from app.diagnosis.fault_tree_schemas import (
    EvidenceCriterion,
    FaultTreeDefinition,
    FaultTreeEvaluation,
    GuidanceHint,
    MatchedCauseEvidence,
    RankedCause,
)
from app.diagnosis.schemas import DiagnosisContext, DiagnosisOutcome


@dataclass(frozen=True)
class FaultFactResult:
    value: float
    details: list[dict[str, Any]]


def _diagnosis_error_count(
    context: DiagnosisContext, diagnosis: DiagnosisOutcome, params: dict[str, Any]
) -> FaultFactResult:
    del context
    error_type = params.get("error_type")
    matches = [item for item in diagnosis.matches if item.error_type == error_type]
    return FaultFactResult(
        float(len(matches)),
        [
            {"rule_id": item.rule_id, "error_type": item.error_type, "summary": item.summary}
            for item in matches
        ],
    )


def _log_event_count(
    context: DiagnosisContext, diagnosis: DiagnosisOutcome, params: dict[str, Any]
) -> FaultFactResult:
    del diagnosis
    event_code = params.get("event_code")
    matches = [item for item in context.logs if item.event_code == event_code]
    return FaultFactResult(
        float(len(matches)),
        [
            {
                "log_id": item.id,
                "event_code": item.event_code,
                "message": item.message,
                "occurred_at": item.occurred_at.isoformat(),
            }
            for item in matches
        ],
    )


FACTS: dict[
    str,
    Callable[[DiagnosisContext, DiagnosisOutcome, dict[str, Any]], FaultFactResult],
] = {
    "diagnosis_error_count": _diagnosis_error_count,
    "log_event_count": _log_event_count,
}
OPERATORS = {"eq": eq, "gte": ge, "gt": gt, "lte": le, "lt": lt}


def _match_evidence(
    criterion: EvidenceCriterion,
    context: DiagnosisContext,
    diagnosis: DiagnosisOutcome,
) -> Optional[MatchedCauseEvidence]:
    result = FACTS[criterion.fact](context, diagnosis, criterion.params)
    if not OPERATORS[criterion.operator](result.value, criterion.value):
        return None
    return MatchedCauseEvidence(
        fact=criterion.fact,
        description=criterion.description,
        weight=criterion.weight,
        observed_value=result.value,
        details=result.details,
    )


def _hint_level(tree: FaultTreeDefinition, failure_count: int, duration: int) -> int:
    level = 1
    for threshold in sorted(tree.escalation, key=lambda item: item.level):
        if (
            failure_count >= threshold.min_failure_count
            or duration >= threshold.min_duration_seconds
        ):
            level = threshold.level
    return level


def evaluate_fault_tree(
    tree: FaultTreeDefinition,
    context: DiagnosisContext,
    diagnosis: DiagnosisOutcome,
    *,
    failure_count: int,
    anomaly_duration_seconds: int,
) -> Optional[FaultTreeEvaluation]:
    if not tree.enabled:
        return None
    triggers = [_match_evidence(item, context, diagnosis) for item in tree.trigger]
    if not all(item is not None for item in triggers):
        return None

    causes = []
    for cause in tree.causes:
        evidence = [
            matched
            for criterion in cause.evidence
            if (matched := _match_evidence(criterion, context, diagnosis)) is not None
        ]
        score = min(100, sum(item.weight for item in evidence))
        if score == 0:
            continue
        confidence = "high" if score >= 70 else "medium" if score >= 40 else "low"
        causes.append(
            RankedCause(
                cause_id=cause.id,
                title=cause.title,
                score=score,
                confidence=confidence,
                evidence=evidence,
            )
        )
    causes.sort(key=lambda item: (-item.score, item.cause_id))
    level = _hint_level(tree, failure_count, anomaly_duration_seconds)
    cause_by_id = {cause.id: cause for cause in tree.causes}
    return FaultTreeEvaluation(
        tree_id=tree.id,
        tree_title=tree.title,
        tree_status=tree.status,
        hint_level=level,
        failure_count=failure_count,
        anomaly_duration_seconds=anomaly_duration_seconds,
        teacher_intervention_required=level == 4,
        ranked_causes=causes,
        hints=[
            GuidanceHint(
                cause_id=cause.cause_id,
                level=level,
                text=cause_by_id[cause.cause_id].hints[level],
            )
            for cause in causes
        ],
    )
