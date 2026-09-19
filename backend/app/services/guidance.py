from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.diagnosis.fault_tree import evaluate_fault_tree
from app.diagnosis.fault_tree_loader import (
    load_fault_trees,
    load_fault_trees_from_document,
)
from app.diagnosis.fault_tree_schemas import FaultTreeEvaluation
from app.diagnosis.schemas import DiagnosisContext, DiagnosisOutcome
from app.models.base import utc_now
from app.models.device import Device
from app.models.diagnosis_result import DiagnosisResult
from app.models.guidance_history import GuidanceHistory
from app.services.diagnosis_episode import (
    confirmed_recovery,
    diagnosis_scope,
    failure_evidence_keys,
    lifecycle_lock,
    upsert_episode,
)


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


def _matching_history(
    db: Session, diagnosis: DiagnosisResult, tree_id: str, tree_hash: str, window_seconds: int
) -> list[GuidanceHistory]:
    since = _aware(diagnosis.evaluated_at) - timedelta(seconds=window_seconds)
    rows = db.scalars(
        select(GuidanceHistory)
        .join(DiagnosisResult)
        .where(
            GuidanceHistory.device_id == diagnosis.device_id,
            GuidanceHistory.fault_tree_id == tree_id,
            GuidanceHistory.fault_tree_hash == tree_hash,
            DiagnosisResult.episode_id == diagnosis.episode_id,
            DiagnosisResult.evaluated_at >= since,
        )
        .order_by(GuidanceHistory.created_at.desc(), GuidanceHistory.id.desc())
    ).all()
    rows = [
        row for row in rows if diagnosis_scope(row.diagnosis_result) == diagnosis_scope(diagnosis)
    ]
    if rows:
        intervening = db.scalars(
            select(DiagnosisResult).where(
                DiagnosisResult.device_id == diagnosis.device_id,
                DiagnosisResult.evaluated_at > rows[0].diagnosis_result.evaluated_at,
                DiagnosisResult.evaluated_at <= diagnosis.evaluated_at,
            )
        ).all()
        if any(confirmed_recovery(item, rows[0].diagnosis_result) for item in intervening):
            return []
    return rows


def _tree_evidence_keys(diagnosis, tree):
    error_types = {
        item.params.get("error_type")
        for item in tree.trigger
        if item.fact == "diagnosis_error_count"
    }
    keys = failure_evidence_keys(diagnosis, error_types) if error_types else set()
    for criterion in tree.trigger:
        if criterion.fact == "log_event_count":
            keys.update(
                f"log_id:{item['id']}"
                for item in diagnosis.context_snapshot.get("logs", [])
                if item.get("event_code") == criterion.params.get("event_code")
            )
        elif criterion.fact == "event_type_count":
            keys.update(
                f"event_id:{item['id']}"
                for item in diagnosis.context_snapshot.get("events", [])
                if item.get("type") == criterion.params.get("event_type")
            )
        elif criterion.fact == "expected_behavior_violation_count":
            # The corresponding rule already persists the matched behavior references.
            keys.update(failure_evidence_keys(diagnosis, error_types))
    return keys


def generate_guidance(db, device, diagnosis_result, *, settings=None):
    with lifecycle_lock(db, diagnosis_result):
        episode = upsert_episode(db, device, diagnosis_result, [], settings or get_settings())
        records = _generate_guidance(db, device, diagnosis_result, episode=episode)
        upsert_episode(db, device, diagnosis_result, records, settings or get_settings())
        return records


def _generate_guidance(
    db: Session, device: Device, diagnosis_result: DiagnosisResult, *, episode=None
) -> list[GuidanceHistory]:
    existing = db.scalars(
        select(GuidanceHistory)
        .where(GuidanceHistory.diagnosis_result_id == diagnosis_result.id)
        .order_by(GuidanceHistory.fault_tree_id)
    ).all()
    if existing:
        return list(existing)

    context, diagnosis = _restore_diagnosis(diagnosis_result)
    if context.package_fault_tree_document:
        tree_set, tree_hash = load_fault_trees_from_document(
            context.package_fault_tree_document,
            context=context,
        )
    else:
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
        history = _matching_history(
            db, diagnosis_result, tree.id, tree_hash, tree.continuity_window_seconds
        )
        previous = history[0] if history else None
        if previous is not None:
            known = set().union(
                *(_tree_evidence_keys(item.diagnosis_result, tree) for item in history)
            )
            new_failure = bool(_tree_evidence_keys(diagnosis_result, tree) - known)
            failure_count = previous.failure_count + int(new_failure)
            first_detected_at = _aware(previous.first_detected_at)
        else:
            failure_count = 1
            first_detected_at = evaluated_at
        duration = (
            previous.anomaly_duration_seconds
            if previous is not None and episode is not None and episode.status == "resolved"
            else max(0, int((evaluated_at - first_detected_at).total_seconds()))
        )
        if previous is not None:
            duration = max(duration, previous.anomaly_duration_seconds)
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
