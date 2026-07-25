from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.models.device import Device
from app.models.diagnosis_episode import DiagnosisEpisode
from app.models.diagnosis_result import DiagnosisResult
from app.models.guidance_history import GuidanceHistory


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def _primary_error(diagnosis: DiagnosisResult) -> str | None:
    if diagnosis.matched_rules:
        return str(diagnosis.matched_rules[0].get("error_type") or "") or None
    has_error_log = any(
        str(item.get("level", "")).upper() in {"ERROR", "CRITICAL"}
        for item in diagnosis.context_snapshot.get("logs", [])
    )
    return "UNCLASSIFIED_ANOMALY" if has_error_log else None


def upsert_episode(
    db: Session,
    device: Device,
    diagnosis: DiagnosisResult,
    guidance: list[GuidanceHistory],
    settings: Settings,
) -> DiagnosisEpisode | None:
    error_code = _primary_error(diagnosis)
    if error_code is None:
        active = db.scalars(
            select(DiagnosisEpisode).where(
                DiagnosisEpisode.device_id == device.id,
                DiagnosisEpisode.status.in_(("open", "escalated")),
            )
        ).all()
        for item in active:
            item.status = "resolved"
            item.resolved_at = _aware(diagnosis.evaluated_at)
            item.resolution_source = "deterministic_recovery"
        if active:
            db.commit()
        return None
    evaluated_at = _aware(diagnosis.evaluated_at)
    template = diagnosis.context_snapshot.get("experiment_template") or {}
    experiment_id = template.get("template_id")
    cutoff = evaluated_at - timedelta(seconds=settings.diagnosis_episode_window_seconds)
    episode = db.scalar(
        select(DiagnosisEpisode)
        .where(
            DiagnosisEpisode.device_id == device.id,
            DiagnosisEpisode.primary_error_code == error_code,
            DiagnosisEpisode.status.in_(("open", "escalated")),
            DiagnosisEpisode.last_seen_at >= cutoff,
        )
        .order_by(DiagnosisEpisode.last_seen_at.desc())
        .limit(1)
    )
    hint_level = max((item.hint_level for item in guidance), default=1)
    failure_count = max((item.failure_count for item in guidance), default=1)
    if episode is None or episode.experiment_id != experiment_id:
        episode = DiagnosisEpisode(
            device_id=device.id,
            experiment_id=experiment_id,
            primary_error_code=error_code,
            status="escalated" if hint_level >= 4 else "open",
            started_at=evaluated_at,
            last_seen_at=evaluated_at,
            failure_count=failure_count,
            latest_context_fingerprint=diagnosis.input_fingerprint,
            current_hint_level=hint_level,
            last_diagnosis_result_id=diagnosis.id,
            ai_call_count=0,
        )
        db.add(episode)
    else:
        previous_result_id = episode.last_diagnosis_result_id
        episode.last_seen_at = max(_aware(episode.last_seen_at), evaluated_at)
        episode.failure_count = max(
            episode.failure_count + (1 if previous_result_id != diagnosis.id else 0),
            failure_count,
        )
        episode.latest_context_fingerprint = diagnosis.input_fingerprint
        episode.current_hint_level = max(episode.current_hint_level, hint_level)
        episode.last_diagnosis_result_id = diagnosis.id
        if episode.current_hint_level >= 4:
            episode.status = "escalated"
    db.commit()
    db.refresh(episode)
    return episode


def resolve_episode(db: Session, episode: DiagnosisEpisode, source: str) -> DiagnosisEpisode:
    episode.status = "resolved"
    episode.resolved_at = datetime.now(timezone.utc)
    episode.resolution_source = source
    db.commit()
    db.refresh(episode)
    return episode
