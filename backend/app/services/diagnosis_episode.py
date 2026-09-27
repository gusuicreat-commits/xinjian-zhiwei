from __future__ import annotations

import hashlib
import json
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timedelta, timezone
from threading import RLock

from sqlalchemy import create_engine, func, select, text
from sqlalchemy.orm import Session, object_session
from sqlalchemy.pool import NullPool

from app.core.config import Settings
from app.models.device import Device
from app.models.diagnosis_episode import DiagnosisEpisode, DiagnosisIssue
from app.models.diagnosis_feedback import DiagnosisFeedback
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


def evidence_source_key(item, default_prefix):
    if item.get("source_ref"):
        prefix = {
            "device_log": "log_id",
            "sensor_reading": "reading_id",
            "device_heartbeat": "heartbeat_id",
        }.get(item.get("source"))
        prefix = prefix or f"source:{item.get('source') or 'unknown'}"
        return f"{prefix}:{item['source_ref']}"
    return f"{default_prefix}:{item.get('id')}"


def failure_evidence_keys(
    diagnosis: DiagnosisResult, error_types: set[str] | None = None
) -> set[str]:
    """Count new source evidence, never result IDs or changing evaluation timestamps."""
    keys: set[str] = set()
    aliases = {}
    for field, prefix in (
        ("events", "event_id"),
        ("observations", "reading_id"),
        ("logs", "log_id"),
        ("readings", "reading_id"),
    ):
        for item in (diagnosis.context_snapshot or {}).get(field, []):
            aliases[(prefix, str(item.get("id")))] = evidence_source_key(item, prefix)

    def visit(value):
        if isinstance(value, dict):
            if value.get("source_ref"):
                keys.add(evidence_source_key(value, "source_ref"))
                return  # Generated IDs are aliases, not additional observations.
            for key, item in value.items():
                if key in {"log_id", "reading_id", "event_id", "source_ref"} and item:
                    keys.add(aliases.get((key, str(item)), f"{key}:{item}"))
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
    if snapshot.get("recheck_recovery_allowed") is False:
        return False
    assessment = snapshot.get("normal_assessment") or {}
    checks = assessment.get("checks") or []
    if (
        diagnosis_scope(diagnosis) != diagnosis_scope(previous)
        or diagnosis.ruleset_hash != previous.ruleset_hash
        or _primary_error(diagnosis) is not None
        or assessment.get("status") != "normal"
        or not checks
        or any(c.get("status") != "satisfied" for c in checks)
        or _aware(diagnosis.evaluated_at) <= _aware(previous.evaluated_at)
    ):
        return False
    from app.services.recovery_evidence import fresh_related_evidence

    return fresh_related_evidence(
        snapshot,
        previous.context_snapshot or {},
        [group["scope"] for group in _issue_groups(previous).values()],
        previous.evaluated_at,
        diagnosis.evaluated_at,
    )


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
    if diagnosis.issue_model_version == 2:
        return _upsert_issues(db, device, diagnosis, guidance)
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
                finish_problem(
                    item, item.evidence_revision, "deterministic_recovery", recovery=diagnosis
                )
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


def episode_attempt_count(db, episode_id):
    """Committed, authorized requests count once, including resumable pending work."""
    if not episode_id:
        return 0
    return (
        db.scalar(
            select(func.count(DiagnosisFeedback.id)).where(
                DiagnosisFeedback.episode_id == episode_id,
                DiagnosisFeedback.action == "unresolved",
            )
        )
        or 0
    )


def apply_episode_feedback(db, diagnosis, feedback):
    """Called once while saving a new feedback row under the lifecycle lock."""
    links = issue_links(db, diagnosis)
    if links:
        if getattr(feedback, "episode_id", None) is None:
            if len(links) != 1:
                raise EpisodeFeedbackConflict(
                    "Select one episode for feedback on multiple problems"
                )
            feedback.episode_id = links[0].episode_id
        link = next((i for i in links if i.episode_id == feedback.episode_id), None)
        if link is None:
            raise EpisodeFeedbackConflict("Episode does not belong to this diagnosis")
        episode = db.get(DiagnosisEpisode, link.episode_id)
        revision = link.evidence_revision
    else:
        episode = episode_for_diagnosis(db, diagnosis)
        if getattr(feedback, "episode_id", None) and (
            episode is None or feedback.episode_id != episode.id
        ):
            raise EpisodeFeedbackConflict("Episode does not belong to this diagnosis")
        revision = diagnosis.episode_evidence_revision
    if episode is None:
        if diagnosis.episode_evidence_revision is not None and _primary_error(diagnosis) is None:
            return  # A new diagnosis without an anomaly needs no fault lifecycle transition.
        raise EpisodeFeedbackConflict(
            "Historical diagnosis has no recorded episode ownership; run a new diagnosis"
        )
    db.refresh(episode)
    if episode.status not in {"open", "escalated"}:
        raise EpisodeFeedbackConflict(
            "This problem is closed; replay the original receipt or run a new diagnosis"
        )
    # Bind before counting: compatibility feedback also has explicit ownership.
    feedback.episode_id = episode.id
    db.flush()
    if feedback.action == "unresolved":
        episode.current_hint_level = max(
            episode.current_hint_level, min(4, 1 + episode_attempt_count(db, episode.id))
        )
        if episode.current_hint_level == 4:
            episode.status = "escalated"
    if feedback.action == "resolved":
        finish_problem(episode, revision, "student_feedback")
    elif feedback.action == "request_teacher_help":
        episode.status = "escalated"
        episode.current_hint_level = 4


def finish_problem(episode, expected_revision, source, *, recovery=None):
    """Shared transition; callers serialize the scope and commit their audit together."""
    if episode.status not in {"open", "escalated"}:
        raise EpisodeFeedbackConflict("problem is no longer active")
    if expected_revision is None or expected_revision != episode.evidence_revision:
        raise EpisodeFeedbackConflict("New evidence is available; resolve the latest diagnosis")
    if source not in {
        "student_feedback",
        "teacher_report",
        "teacher_verified_recovery",
        "deterministic_recovery",
    }:
        raise EpisodeFeedbackConflict("unsupported resolution authority")
    if source in {"teacher_verified_recovery", "deterministic_recovery"}:
        if recovery is None or not confirmed_recovery(recovery, episode.last_diagnosis_result):
            raise EpisodeFeedbackConflict(
                "fresh recovery evidence does not satisfy this problem's scope"
            )
    episode.status = "resolved"
    episode.resolved_at = _aware(recovery.evaluated_at) if recovery else datetime.now(timezone.utc)
    episode.resolution_source = source


def issue_links(db, diagnosis):
    return list(
        db.scalars(
            select(DiagnosisIssue)
            .where(DiagnosisIssue.diagnosis_result_id == diagnosis.id)
            .order_by(DiagnosisIssue.error_type, DiagnosisIssue.issue_key)
        )
    )


def diagnosis_issues(db, diagnosis):
    return [
        {
            "id": link.episode_id,
            "error_type": link.error_type,
            "scope": link.scope,
            "status": link.episode.status,
            "evidence_revision": link.evidence_revision,
            "current_evidence_revision": link.episode.evidence_revision,
            "failure_count": link.episode.failure_count,
            "resolution_source": link.episode.resolution_source,
            "observation_state": link.observation_state,
        }
        for link in issue_links(db, diagnosis)
    ]


def _issue_groups(diagnosis):
    """Rules define anomaly groups. Never infer a common root from co-occurrence."""
    groups = {}
    for match in diagnosis.matched_rules:
        error = str(match.get("error_type") or "UNCLASSIFIED_ANOMALY")
        scope = match.get("scope") or {"kind": "unknown", "keys": []}
        scope = {"kind": scope.get("kind", "unknown"), "keys": sorted(scope.get("keys", []))}
        components = set()
        interfaces = set()

        def collect(value, components=components, interfaces=interfaces):
            if isinstance(value, dict):
                if value.get("component_id"):
                    components.add(value["component_id"])
                if value.get("interface_id"):
                    interfaces.add(value["interface_id"])
                for child in value.values():
                    collect(child)
            elif isinstance(value, list):
                for child in value:
                    collect(child)

        collect(match.get("evidence", []))
        if len(components) == 1:
            scope = {"kind": "component", "keys": sorted(components)}
        elif not components and len(interfaces) == 1:
            scope = {"kind": "interface", "keys": sorted(interfaces)}
        elif components or interfaces:
            # An aggregate rule hit does not establish which individual source
            # satisfies that rule on its own. Preserve its ambiguity explicitly.
            scope = {"kind": "aggregate", "keys": sorted(components | interfaces)}
        key = hashlib.sha256(json.dumps([error, scope], sort_keys=True).encode()).hexdigest()
        groups.setdefault(key, {"error": error, "scope": scope, "matches": []})["matches"].append(
            match
        )
    if not groups and _primary_error(diagnosis):
        groups["unclassified"] = {
            "error": "UNCLASSIFIED_ANOMALY",
            "scope": {"kind": "unknown", "keys": []},
            "matches": [],
        }
    return groups


def _group_evidence(diagnosis, group):
    # A lightweight view limits evidence collection to exactly this rule group.
    from types import SimpleNamespace

    view = SimpleNamespace(
        matched_rules=group["matches"], context_snapshot=diagnosis.context_snapshot
    )
    return failure_evidence_keys(view)


def _new_evidence_after(diagnosis, keys, cutoff):
    """A late delivery is not recurrence; only an observed event after closure is."""
    snapshot = diagnosis.context_snapshot or {}
    for field, prefix, time_field in (
        ("logs", "log_id", "occurred_at"),
        ("readings", "reading_id", "observed_at"),
        ("events", "event_id", "occurred_at"),
        ("observations", "reading_id", "observed_at"),
    ):
        for item in snapshot.get(field, []):
            candidates = {evidence_source_key(item, prefix)}
            if not candidates.intersection(keys):
                continue
            time_quality = snapshot.get("recheck_source_time_quality") or {}
            source = item.get("source") or {
                "logs": "device_log",
                "readings": "sensor_reading",
            }.get(field)
            source_key = f"{source}:{item.get('source_ref') or item.get('id')}"
            if time_quality.get(source_key) != "device_reported":
                continue
            value = item.get(time_field)
            if value:
                try:
                    observed = _aware(datetime.fromisoformat(str(value).replace("Z", "+00:00")))
                except ValueError:
                    continue
                if _aware(cutoff) < observed <= _aware(diagnosis.evaluated_at):
                    return True
    return False


def _upsert_issues(db, device, diagnosis, guidance):
    existing = issue_links(db, diagnosis)
    if existing:
        for link in existing:
            relevant = [g for g in guidance if g.episode_id == link.episode_id]
            episode = link.episode
            db.refresh(episode)
            if relevant and episode.status in {"open", "escalated"}:
                episode.current_hint_level = max(
                    episode.current_hint_level, max(g.hint_level for g in relevant)
                )
                if episode.current_hint_level == 4:
                    episode.status = "escalated"
        db.commit()
        return episode_for_diagnosis(db, diagnosis)
    evaluated = _aware(diagnosis.evaluated_at)
    for key, group in sorted(_issue_groups(diagnosis).items()):
        scope_key = hashlib.sha256(
            json.dumps(
                [diagnosis_scope(diagnosis), diagnosis.ruleset_hash, key], sort_keys=True
            ).encode()
        ).hexdigest()
        previous = db.scalar(
            select(DiagnosisEpisode)
            .where(DiagnosisEpisode.scope_key == scope_key)
            .order_by(DiagnosisEpisode.started_at.desc(), DiagnosisEpisode.id.desc())
        )
        history = list(
            db.scalars(
                select(DiagnosisIssue)
                .join(DiagnosisEpisode, DiagnosisIssue.episode_id == DiagnosisEpisode.id)
                .where(DiagnosisEpisode.scope_key == scope_key)
            )
        )
        known = {k for item in history for k in item.evidence_keys}
        keys = _group_evidence(diagnosis, group)
        new_evidence = bool(keys - known)
        late_or_unverified = False
        if previous and previous.status == "resolved" and new_evidence:
            new_evidence = bool(
                previous.resolved_at
                and _new_evidence_after(diagnosis, keys - known, previous.resolved_at)
            )
            late_or_unverified = not new_evidence
        # An open process does not expire just because sampling stopped.
        if previous and (previous.status in {"open", "escalated"} or not new_evidence):
            episode = previous
            if episode.status != "resolved":
                episode.failure_count += int(new_evidence)
                episode.evidence_revision += int(new_evidence)
                if evaluated >= _aware(episode.last_seen_at):
                    episode.last_seen_at = evaluated
                    episode.last_diagnosis_result_id = diagnosis.id
                    episode.latest_context_fingerprint = diagnosis.input_fingerprint
        else:
            episode = DiagnosisEpisode(
                device_id=device.id,
                experiment_id=diagnosis.experiment_id,
                primary_error_code=group["error"],
                scope_key=scope_key,
                status="open",
                started_at=evaluated,
                last_seen_at=evaluated,
                failure_count=1,
                evidence_revision=1,
                latest_context_fingerprint=diagnosis.input_fingerprint,
                current_hint_level=1,
                last_diagnosis_result_id=diagnosis.id,
                ai_call_count=0,
            )
            db.add(episode)
            db.flush()
        later_keys = {
            k
            for item in history
            if item.episode_id == episode.id
            and _aware(db.get(DiagnosisResult, item.diagnosis_result_id).evaluated_at) >= evaluated
            for k in item.evidence_keys
        }
        link = DiagnosisIssue(
            diagnosis_result_id=diagnosis.id,
            episode_id=episode.id,
            issue_key=key,
            error_type=group["error"],
            scope=group["scope"],
            evidence_keys=sorted(keys),
            evidence_revision=episode.evidence_revision if later_keys.issubset(keys) else None,
            observation_state="late_or_unverified" if late_or_unverified else "current",
        )
        db.add(link)
    db.flush()
    links = issue_links(db, diagnosis)
    if links:
        # Compatibility display only; all writes use the selected association.
        primary = next(
            (link for link in links if link.error_type == _primary_error(diagnosis)), links[0]
        )
        diagnosis.episode_id = primary.episode_id
        diagnosis.episode_evidence_revision = primary.evidence_revision
    else:
        for episode in db.scalars(
            select(DiagnosisEpisode).where(
                DiagnosisEpisode.device_id == device.id,
                DiagnosisEpisode.status.in_(["open", "escalated"]),
            )
        ):
            if confirmed_recovery(diagnosis, episode.last_diagnosis_result):
                finish_problem(
                    episode, episode.evidence_revision, "deterministic_recovery", recovery=diagnosis
                )
    db.commit()
    return episode_for_diagnosis(db, diagnosis)


def resolve_episode(db: Session, episode: DiagnosisEpisode, source: str) -> DiagnosisEpisode:
    episode.status = "resolved"
    episode.resolved_at = datetime.now(timezone.utc)
    episode.resolution_source = source
    db.commit()
    db.refresh(episode)
    return episode
