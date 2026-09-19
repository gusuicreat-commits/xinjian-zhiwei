from __future__ import annotations

import hashlib
import json
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timedelta, timezone
from threading import RLock

from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session, object_session
from sqlalchemy.pool import NullPool

from app.core.config import Settings
from app.models.device import Device
from app.models.diagnosis_episode import DiagnosisEpisode
from app.models.diagnosis_result import DiagnosisResult
from app.models.diagnosis_workflow import DiagnosisWorkflowRun
from app.models.guidance_history import GuidanceHistory

_LIFECYCLE_LOCKS = [RLock() for _ in range(64)]
_HELD_SCOPES = ContextVar("episode_lifecycle_scopes", default=frozenset())


class EpisodeFeedbackConflict(ValueError):
    pass


@contextmanager
def lifecycle_lock(db: Session, diagnosis: DiagnosisResult):
    """Serialize diagnosis and feedback transitions across their existing commits."""
    scope = json.dumps(diagnosis_scope(diagnosis), sort_keys=True)
    key = int.from_bytes(hashlib.sha256(scope.encode()).digest()[:8], "big", signed=True)
    if key in _HELD_SCOPES.get():
        yield
        return
    db.flush()
    token = _HELD_SCOPES.set(_HELD_SCOPES.get() | {key})
    try:
        bind = db.get_bind()
        if bind.dialect.name == "postgresql":
            engine = create_engine(getattr(bind, "engine", bind).url, poolclass=NullPool)
            try:
                with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
                    conn.execute(text("SELECT pg_advisory_lock(:key)"), {"key": key})
                    try:
                        db.refresh(diagnosis)
                        yield
                    finally:
                        conn.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": key})
            finally:
                engine.dispose()
        else:
            with _LIFECYCLE_LOCKS[key % len(_LIFECYCLE_LOCKS)]:
                db.refresh(diagnosis)
                yield
    finally:
        _HELD_SCOPES.reset(token)


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def diagnosis_scope(diagnosis: DiagnosisResult) -> tuple:
    """Keep historical counters and recovery within the same immutable input scope."""
    snapshot = diagnosis.context_snapshot or {}
    scope = snapshot.get("feedback_scope")
    db = object_session(diagnosis)
    if scope is None and db is not None:
        workflow = db.scalar(
            select(DiagnosisWorkflowRun)
            .where(DiagnosisWorkflowRun.diagnosis_result_id == diagnosis.id)
            .order_by(DiagnosisWorkflowRun.created_at.desc())
            .limit(1)
        )
        if workflow is not None:
            scope = {
                "experiment_session_id": workflow.experiment_session_id,
                "student_user_id": workflow.student_user_id,
                "device_id": workflow.device_id,
            }
    return (
        diagnosis.device_id,
        diagnosis.experiment_id,
        diagnosis.experiment_version,
        diagnosis.experiment_version_id,
        diagnosis.experiment_definition_hash,
        snapshot.get("experiment_package_hash"),
        diagnosis.is_test_data,
        json.dumps(scope, sort_keys=True),
        json.dumps(snapshot.get("experiment_template"), sort_keys=True),
    )


def failure_evidence_keys(
    diagnosis: DiagnosisResult, error_types: set[str] | None = None
) -> set[str]:
    """Count new source evidence, never result IDs or changing evaluation timestamps."""
    keys: set[str] = set()

    def visit(value):
        if isinstance(value, dict):
            for key, item in value.items():
                if key in {"log_id", "reading_id", "event_id", "source_ref"} and item:
                    keys.add(f"{key}:{item}")
                elif key in {"evidence_refs", "source_refs"} and isinstance(item, list):
                    keys.update(f"ref:{ref}" for ref in item)
                else:
                    visit(item)
        elif isinstance(value, list):
            for item in value:
                visit(item)

    for match in diagnosis.matched_rules:
        if error_types is not None and match.get("error_type") not in error_types:
            continue
        before = set(keys)
        visit(match)
        if keys == before:
            # A stable rule fact (e.g. one offline interval) is not a new observation
            # merely because its elapsed duration/evaluation timestamp changed.
            anchor = (diagnosis.context_snapshot or {}).get("last_seen_at")
            keys.add(f"rule:{match.get('rule_id')}:{anchor}")
    if not diagnosis.matched_rules:
        keys.update(
            f"log_id:{item['id']}"
            for item in (diagnosis.context_snapshot or {}).get("logs", [])
            if item.get("id") and str(item.get("level", "")).upper() in {"ERROR", "CRITICAL"}
        )
    return keys


def confirmed_recovery(diagnosis: DiagnosisResult, previous: DiagnosisResult) -> bool:
    snapshot = diagnosis.context_snapshot or {}
    assessment = snapshot.get("normal_assessment") or {}
    checks = assessment.get("checks") or []
    if (
        diagnosis_scope(diagnosis) != diagnosis_scope(previous)
        or _primary_error(diagnosis) is not None
        or assessment.get("status") != "normal"
        or not checks
        or any(c.get("status") != "satisfied" for c in checks)
        or _aware(diagnosis.evaluated_at) <= _aware(previous.evaluated_at)
    ):
        return False
    # An empty/restricted window and a later evaluation time are not recovery evidence.
    for name in ("observations", "readings", "heartbeats"):
        for item in snapshot.get(name, []):
            value = item.get("observed_at")
            if value:
                observed = _aware(datetime.fromisoformat(str(value).replace("Z", "+00:00")))
                if _aware(previous.evaluated_at) < observed <= _aware(diagnosis.evaluated_at):
                    return True
    return False


def _primary_error(diagnosis: DiagnosisResult) -> str | None:
    if diagnosis.matched_rules:
        return str(diagnosis.matched_rules[0].get("error_type") or "") or None
    has_error_log = any(
        str(item.get("level", "")).upper() in {"ERROR", "CRITICAL"}
        for item in diagnosis.context_snapshot.get("logs", [])
    )
    return "UNCLASSIFIED_ANOMALY" if has_error_log else None


def episode_for_diagnosis(db: Session, diagnosis: DiagnosisResult) -> DiagnosisEpisode | None:
    """Read explicit ownership only; never backfill an immutable historical diagnosis."""
    return db.get(DiagnosisEpisode, diagnosis.episode_id) if diagnosis.episode_id else None


def upsert_episode(
    db: Session,
    device: Device,
    diagnosis: DiagnosisResult,
    guidance: list[GuidanceHistory],
    settings: Settings,
) -> DiagnosisEpisode | None:
    with lifecycle_lock(db, diagnosis):
        return _upsert_episode_locked(db, device, diagnosis, guidance, settings)


def _upsert_episode_locked(db, device, diagnosis, guidance, settings):
    if diagnosis.episode_id is None and diagnosis.episode_evidence_revision is None:
        # NULL is a pre-lifecycle historical row. New inserts explicitly start at 0.
        return None
    bound = db.get(DiagnosisEpisode, diagnosis.episode_id) if diagnosis.episode_id else None
    if bound is not None:
        db.refresh(bound)
        if (
            bound.status in {"open", "escalated"}
            and bound.last_diagnosis_result_id == diagnosis.id
            and guidance
        ):
            bound.current_hint_level = max(
                bound.current_hint_level, max(item.hint_level for item in guidance)
            )
            if bound.current_hint_level == 4:
                bound.status = "escalated"
        db.commit()
        return bound
    error_code = _primary_error(diagnosis)
    candidates = db.scalars(
        select(DiagnosisEpisode)
        .where(
            DiagnosisEpisode.device_id == device.id,
        )
        .order_by(DiagnosisEpisode.started_at.desc())
        .execution_options(populate_existing=True)
    ).all()
    scoped = [
        item
        for item in candidates
        if diagnosis_scope(item.last_diagnosis_result) == diagnosis_scope(diagnosis)
    ]
    if error_code is None:
        for item in scoped:
            if item.status in {"open", "escalated"} and confirmed_recovery(
                diagnosis, item.last_diagnosis_result
            ):
                item.status = "resolved"
                item.resolved_at = _aware(diagnosis.evaluated_at)
                item.resolution_source = "deterministic_recovery"
        db.commit()
        return None
    previous = next((item for item in scoped if item.primary_error_code == error_code), None)
    historical = db.scalars(
        select(DiagnosisResult).where(
            DiagnosisResult.device_id == device.id,
            DiagnosisResult.id != diagnosis.id,
            DiagnosisResult.episode_id.is_not(None),
        )
    ).all()
    historical = [
        item for item in historical if diagnosis_scope(item) == diagnosis_scope(diagnosis)
    ]
    primary_known = set().union(*(failure_evidence_keys(item, {error_code}) for item in historical))
    new_failure = bool(failure_evidence_keys(diagnosis, {error_code}) - primary_known)
    evaluated_at = _aware(diagnosis.evaluated_at)
    if previous is not None and not new_failure and previous.status == "resolved":
        # Replaying evidence from a closed incident is not a new incident.
        diagnosis.episode_id = previous.id
        diagnosis.episode_evidence_revision = previous.evidence_revision
        db.commit()
        return previous
    cutoff = evaluated_at - timedelta(seconds=settings.diagnosis_episode_window_seconds)
    episode = (
        previous
        if (
            previous is not None
            and previous.status in {"open", "escalated"}
            and (_aware(previous.last_seen_at) >= cutoff or not new_failure)
        )
        else None
    )
    if episode is None:
        template = diagnosis.context_snapshot.get("experiment_template") or {}
        episode = DiagnosisEpisode(
            device_id=device.id,
            experiment_id=diagnosis.experiment_id or template.get("template_id"),
            primary_error_code=error_code,
            status="open",
            started_at=evaluated_at,
            last_seen_at=evaluated_at,
            failure_count=1,
            evidence_revision=1,
            latest_context_fingerprint=diagnosis.input_fingerprint,
            current_hint_level=1,
            last_diagnosis_result_id=diagnosis.id,
            ai_call_count=0,
        )
        db.add(episode)
    else:
        episode.failure_count += int(new_failure)
        episode.evidence_revision += int(new_failure)
        if evaluated_at >= _aware(episode.last_seen_at):
            episode.last_seen_at = evaluated_at
            episode.last_diagnosis_result_id = diagnosis.id
            episode.latest_context_fingerprint = diagnosis.input_fingerprint
    db.flush()
    diagnosis.episode_id = episode.id
    # A request may acquire the lock after a newer snapshot has been registered.
    # Do not certify that it saw evidence absent from its immutable input.
    incident_known = set().union(
        *(
            failure_evidence_keys(item, {error_code})
            for item in historical
            if item.episode_id == episode.id and _aware(item.evaluated_at) >= evaluated_at
        )
    )
    diagnosis.episode_evidence_revision = (
        episode.evidence_revision
        if incident_known.issubset(failure_evidence_keys(diagnosis, {error_code}))
        else None
    )
    db.commit()
    return episode


def apply_episode_feedback(db, diagnosis, feedback):
    """Called once while saving a new feedback row under the lifecycle lock."""
    episode = episode_for_diagnosis(db, diagnosis)
    if episode is None:
        if diagnosis.episode_evidence_revision is not None and _primary_error(diagnosis) is None:
            return  # A new diagnosis without an anomaly needs no fault lifecycle transition.
        raise EpisodeFeedbackConflict(
            "Historical diagnosis has no recorded episode ownership; run a new diagnosis"
        )
    db.refresh(episode)
    if episode.status not in {"open", "escalated"}:
        return
    if feedback.action == "resolved":
        revision = diagnosis.episode_evidence_revision
        if revision is None or revision != episode.evidence_revision:
            raise EpisodeFeedbackConflict("New evidence is available; resolve the latest diagnosis")
        episode.status = "resolved"
        episode.resolved_at = datetime.now(timezone.utc)
        episode.resolution_source = "student_feedback"
    elif feedback.action == "request_teacher_help":
        episode.status = "escalated"
        episode.current_hint_level = 4


def resolve_episode(db: Session, episode: DiagnosisEpisode, source: str) -> DiagnosisEpisode:
    episode.status = "resolved"
    episode.resolved_at = datetime.now(timezone.utc)
    episode.resolution_source = source
    db.commit()
    db.refresh(episode)
    return episode
