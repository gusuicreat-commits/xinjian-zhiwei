from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.diagnosis.fault_tree import evaluate_fault_tree
from app.diagnosis.fault_tree_loader import load_fault_trees
from app.diagnosis.fault_tree_schemas import FaultTreeEvaluation
from app.diagnosis.schemas import DiagnosisContext, DiagnosisOutcome
from app.models.base import utc_now
from app.models.device import Device
from app.models.diagnosis_result import DiagnosisResult
from app.models.guidance_history import GuidanceHistory


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


def _restore_diagnosis(record: DiagnosisResult) -> tuple[DiagnosisContext, DiagnosisOutcome]:
    return (
        DiagnosisContext.model_validate(record.context_snapshot),
        DiagnosisOutcome.model_validate(
            {
                "ruleset_version": record.ruleset_version,
                "ruleset_hash": record.ruleset_hash,
                "input_fingerprint": record.input_fingerprint,
                "matches": record.matched_rules,
            }
        ),
    )


def _latest_history(db: Session, device_id: str, fault_tree_id: str) -> Optional[GuidanceHistory]:
    return db.scalar(
        select(GuidanceHistory)
        .where(
            GuidanceHistory.device_id == device_id,
            GuidanceHistory.fault_tree_id == fault_tree_id,
        )
        .order_by(GuidanceHistory.created_at.desc(), GuidanceHistory.id.desc())
        .limit(1)
    )


def generate_guidance(
    db: Session, device: Device, diagnosis_result: DiagnosisResult
) -> list[GuidanceHistory]:
    existing = db.scalars(
        select(GuidanceHistory)
        .where(GuidanceHistory.diagnosis_result_id == diagnosis_result.id)
        .order_by(GuidanceHistory.fault_tree_id)
    ).all()
    if existing:
        return list(existing)

    context, diagnosis = _restore_diagnosis(diagnosis_result)
    tree_set, tree_hash = load_fault_trees(context=context if context.experiment_id else None)
    records = []
    evaluated_at = _aware(diagnosis_result.evaluated_at)
    for tree in sorted(tree_set.trees, key=lambda item: item.id):
        probe = evaluate_fault_tree(
            tree,
            context,
            diagnosis,
            failure_count=1,
            anomaly_duration_seconds=0,
        )
        if probe is None:
            continue
        previous = _latest_history(db, device.id, tree.id)
        previous_gap = (
            (evaluated_at - _aware(previous.created_at)).total_seconds()
            if previous is not None
            else None
        )
        if (
            previous is not None
            and previous_gap is not None
            and 0 <= previous_gap <= tree.continuity_window_seconds
        ):
            failure_count = previous.failure_count + 1
            first_detected_at = _aware(previous.first_detected_at)
        else:
            failure_count = 1
            first_detected_at = evaluated_at
        duration = max(0, int((evaluated_at - first_detected_at).total_seconds()))
        evaluation = evaluate_fault_tree(
            tree,
            context,
            diagnosis,
            failure_count=failure_count,
            anomaly_duration_seconds=duration,
        )
        if evaluation is None:
            continue
        record = GuidanceHistory(
            device_id=device.id,
            diagnosis_result_id=diagnosis_result.id,
            fault_tree_id=tree.id,
            fault_tree_title=tree.title,
            fault_tree_status=tree.status,
            fault_tree_version=tree_set.version,
            fault_tree_hash=tree_hash,
            fault_tree_source_id=tree.source_id,
            fault_tree_scope=tree.scope.model_dump(mode="json"),
            first_detected_at=first_detected_at,
            failure_count=evaluation.failure_count,
            anomaly_duration_seconds=evaluation.anomaly_duration_seconds,
            hint_level=evaluation.hint_level,
            teacher_intervention_required=evaluation.teacher_intervention_required,
            ranked_causes=[item.model_dump(mode="json") for item in evaluation.ranked_causes],
            hints=[item.model_dump(mode="json") for item in evaluation.hints],
            is_test_data=diagnosis_result.is_test_data,
            created_at=utc_now(),
        )
        db.add(record)
        records.append(record)
    db.commit()
    for record in records:
        db.refresh(record)
    return records


def history_to_evaluation(record: GuidanceHistory) -> FaultTreeEvaluation:
    return FaultTreeEvaluation.model_validate(
        {
            "tree_id": record.fault_tree_id,
            "tree_title": record.fault_tree_title,
            "tree_status": record.fault_tree_status,
            "hint_level": record.hint_level,
            "failure_count": record.failure_count,
            "anomaly_duration_seconds": record.anomaly_duration_seconds,
            "teacher_intervention_required": record.teacher_intervention_required,
            "ranked_causes": record.ranked_causes,
            "hints": record.hints,
            "source_id": record.fault_tree_source_id or "legacy",
            "source_version": record.fault_tree_version,
            "scope": record.fault_tree_scope or {},
        }
    )


def list_device_guidance(db: Session, device: Device) -> list[GuidanceHistory]:
    return list(
        db.scalars(
            select(GuidanceHistory)
            .where(GuidanceHistory.device_id == device.id)
            .order_by(GuidanceHistory.created_at.desc(), GuidanceHistory.id.desc())
        ).all()
    )


def list_interventions(db: Session) -> list[GuidanceHistory]:
    return list(
        db.scalars(
            select(GuidanceHistory)
            .where(GuidanceHistory.teacher_intervention_required.is_(True))
            .order_by(GuidanceHistory.created_at.desc(), GuidanceHistory.id.desc())
        ).all()
    )
