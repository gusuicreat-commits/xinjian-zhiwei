from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session, object_session

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
    _issue_groups,
    confirmed_recovery,
    diagnosis_scope,
    episode_attempt_count,
    evidence_source_key,
    failure_evidence_keys,
    issue_links,
    lifecycle_lock,
    upsert_episode,
)
from app.services.teaching_materials import attach_teaching_materials


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
    db: Session,
    diagnosis: DiagnosisResult,
    tree_id: str,
    tree_hash: str,
    window_seconds: int,
    episode_id: str | None = None,
) -> list[GuidanceHistory]:
    since = _aware(diagnosis.evaluated_at) - timedelta(seconds=window_seconds)
    rows = db.scalars(
        select(GuidanceHistory)
        .join(DiagnosisResult)
        .where(
            GuidanceHistory.device_id == diagnosis.device_id,
            GuidanceHistory.fault_tree_id == tree_id,
            GuidanceHistory.fault_tree_hash == tree_hash,
            GuidanceHistory.episode_id == episode_id,
            (DiagnosisResult.evaluated_at >= since) if episode_id is None else True,
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


def _tree_evidence_keys(diagnosis, tree, episode_id=None):
    error_types = {
        item.params.get("error_type")
        for item in tree.trigger
        if item.fact == "diagnosis_error_count"
    }
    keys = failure_evidence_keys(diagnosis, error_types) if error_types else set()
    for criterion in tree.trigger:
        if criterion.fact == "log_event_count":
            keys.update(
                evidence_source_key(item, "log_id")
                for item in diagnosis.context_snapshot.get("logs", [])
                if item.get("event_code") == criterion.params.get("event_code")
            )
        elif criterion.fact == "event_type_count":
            keys.update(
                evidence_source_key(item, "event_id")
                for item in diagnosis.context_snapshot.get("events", [])
                if item.get("type") == criterion.params.get("event_type")
            )
        elif criterion.fact == "expected_behavior_violation_count":
            # The corresponding rule already persists the matched behavior references.
            keys.update(failure_evidence_keys(diagnosis, error_types))
    if episode_id is not None:
        keys &= set().union(
            *(
                set(link.evidence_keys)
                for link in issue_links(object_session(diagnosis), diagnosis)
                if link.episode_id == episode_id
            )
        )
    return keys


def _observed_span(history, diagnosis, tree, episode_id=None):
    observed = {}
    # Earliest snapshot wins for repeated physical source IDs, even if a later
    # caller supplies a different timestamp for the same source.
    records = [item.diagnosis_result for item in reversed(history)] + [diagnosis]
    for record in records:
        keys = _tree_evidence_keys(record, tree, episode_id)
        for field, prefix, clock in (
            ("logs", "log_id", "occurred_at"),
            ("readings", "reading_id", "observed_at"),
            ("events", "event_id", "occurred_at"),
            ("observations", "reading_id", "observed_at"),
        ):
            for item in record.context_snapshot.get(field, []):
                key = evidence_source_key(item, prefix)
                if key not in keys or key in observed or not item.get(clock):
                    continue
                if (item.get("raw_payload") or {}).get("time_quality") == "server_fallback":
                    continue
                observed[key] = _aware(
                    datetime.fromisoformat(str(item[clock]).replace("Z", "+00:00"))
                )
    values = list(observed.values())
    return max(0, int((max(values) - min(values)).total_seconds())) if values else 0


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
        error_types = {
            c.params.get("error_type") for c in tree.trigger if c.fact == "diagnosis_error_count"
        }
        candidates = [
            link for link in issue_links(db, diagnosis_result) if link.error_type in error_types
        ]
        for link in candidates or [None]:
            target = link.episode if link else None
            scoped_context, scoped_diagnosis = context, diagnosis
            if link is not None:
                group = _issue_groups(diagnosis_result)[link.issue_key]
                scoped_diagnosis = DiagnosisOutcome.model_validate(
                    {
                        **diagnosis.model_dump(),
                        "matches": group["matches"],
                    }
                )
                allowed = set(link.evidence_keys)
                # Keep normal/counter-evidence from the same component too;
                # anomaly source IDs restrict counters, not the complete facts.
                scoped_kind, scoped_keys = link.scope.get("kind"), set(link.scope.get("keys", []))
                for field, prefix in (("events", "event_id"), ("observations", "reading_id")):
                    for item in getattr(context, field):
                        identity = (
                            item.component_id if scoped_kind == "component" else item.interface_id
                        )
                        if identity in scoped_keys:
                            allowed.add(evidence_source_key(item.model_dump(), prefix))
                updates = {}
                for field, key in (
                    ("logs", "log_id"),
                    ("readings", "reading_id"),
                    ("events", "event_id"),
                    ("observations", "reading_id"),
                ):
                    updates[field] = [
                        item
                        for item in getattr(context, field)
                        if scoped_kind not in {"component", "interface"}
                        or evidence_source_key(item.model_dump(), key) in allowed
                    ]
                scoped_context = context.model_copy(update=updates)
            history = (
                _matching_history(
                    db,
                    diagnosis_result,
                    tree.id,
                    tree_hash,
                    tree.continuity_window_seconds,
                    episode_id=target.id if target else None,
                )
                if target or diagnosis_result.issue_model_version != 2
                else []
            )
            previous = history[0] if history else None
            if previous is not None:
                known = set().union(
                    *(
                        _tree_evidence_keys(
                            item.diagnosis_result, tree, target.id if target else None
                        )
                        for item in history
                    )
                )
                new_failure = bool(
                    _tree_evidence_keys(diagnosis_result, tree, target.id if target else None)
                    - known
                )
                failure_count = previous.failure_count + int(new_failure)
                first_detected_at = _aware(previous.first_detected_at)
            else:
                failure_count = 1
                first_detected_at = evaluated_at
            wait_duration = (
                (previous.help_wait_seconds or 0)
                if previous is not None and target is not None and target.status == "resolved"
                else max(0, int((evaluated_at - first_detected_at).total_seconds()))
            )
            if previous is not None:
                wait_duration = max(wait_duration, previous.help_wait_seconds or 0)
            evaluation = evaluate_fault_tree(
                tree,
                scoped_context,
                scoped_diagnosis,
                failure_count=failure_count,
                anomaly_duration_seconds=wait_duration,
                minimum_hint_level=max(
                    target.current_hint_level, min(4, 1 + episode_attempt_count(db, target.id))
                )
                if target
                else 1,
            )
            if evaluation is None:
                continue
            record = GuidanceHistory(
                device_id=device.id,
                diagnosis_result_id=diagnosis_result.id,
                episode_id=target.id if target else None,
                fault_tree_id=tree.id,
                fault_tree_title=tree.title,
                fault_tree_status=tree.status,
                fault_tree_version=tree_set.version,
                fault_tree_hash=tree_hash,
                fault_tree_source_id=tree.source_id,
                fault_tree_scope=tree.scope.model_dump(mode="json"),
                first_detected_at=first_detected_at,
                failure_count=evaluation.failure_count,
                anomaly_duration_seconds=_observed_span(
                    history, diagnosis_result, tree, target.id if target else None
                ),
                help_wait_seconds=wait_duration,
                hint_level=evaluation.hint_level,
                teacher_intervention_required=evaluation.teacher_intervention_required,
                ranked_causes=[item.model_dump(mode="json") for item in evaluation.ranked_causes],
                hints=attach_teaching_materials(
                    db,
                    diagnosis_result,
                    tree_id=tree.id,
                    scope=link.scope if link else {},
                    hints=[item.model_dump(mode="json") for item in evaluation.hints],
                ),
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
            "help_wait_seconds": record.help_wait_seconds,
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
