"""Shared outbound gate. Reserve durably before I/O; never refund an uncertain request."""

from __future__ import annotations

import threading

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.ai.clients import AIClient, AICompletion, AIProviderError
from app.core.config import Settings
from app.models.ai_usage_reservation import AIUsageReservation
from app.models.diagnosis_episode import DiagnosisEpisode
from app.models.diagnosis_result import DiagnosisResult
from app.services.diagnosis_episode import episode_for_diagnosis, issue_links
from app.services.lightweight_diagnosis import budget_allowed, estimate_ai_cost

# PostgreSQL also locks across workers. The process lock supports SQLite's
# single-connection in-memory test mode; file SQLite additionally locks writes.
_reservation_lock = threading.RLock()


class AIQuotaDenied(AIProviderError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def current_delivery_scope(db, diagnosis):
    """Recheck current teaching authority, including on cache hits and late results."""
    from app.models import User
    from app.services.data_scope import (
        assert_student_session_access,
        diagnosis_session,
        is_demo_session,
    )
    from app.services.experiment_packages import load_experiment_package_runtime

    try:
        db.refresh(diagnosis)
        if diagnosis.matched_rules and episode_for_diagnosis(db, diagnosis) is None:
            raise AIQuotaDenied("EPISODE_SCOPE_UNRESOLVED")
        owner = diagnosis_session(db, diagnosis)
        if (diagnosis.context_snapshot or {}).get("feedback_scope") and owner is None:
            raise ValueError("diagnosis owner is unresolved")
        if owner is not None:
            db.refresh(owner)
            student = db.get(User, owner.student_user_id, populate_existing=True)
            if student is None or not student.is_active or owner.status != "active":
                raise ValueError("student session is no longer active")
            if not is_demo_session(db, owner):
                assert_student_session_access(db, student, owner)
        if diagnosis.experiment_version_id:
            load_experiment_package_runtime(db, diagnosis.experiment_version_id)
        from app.services.memory import diagnosis_sources_available

        if not diagnosis_sources_available(db, diagnosis):
            raise AIQuotaDenied("AI_KNOWLEDGE_WITHDRAWN")
        result = []
        for link in issue_links(db, diagnosis):
            db.refresh(link.episode)
            result.append((link.episode_id, link.episode.status, link.episode.evidence_revision))
        return tuple(sorted(result))
    except AIQuotaDenied:
        raise
    except Exception as exc:
        raise AIQuotaDenied("AI_TEACHING_SCOPE_UNAVAILABLE") from exc


def estimate_prompt_tokens(system_prompt: str, user_prompt: str) -> int:
    """Provider-independent estimate, including instructions and Schema, not only data.

    Compatible providers do not share a tokenizer. Actual usage is recorded on
    completion; this estimate is a preflight guard, not a claim of exact tokenization.
    """
    return max(1, (len((system_prompt + user_prompt).encode("utf-8")) + 2) // 3)


class GovernedAIInvocation:
    def __init__(
        self,
        db: Session,
        diagnosis: DiagnosisResult,
        settings: Settings,
        *,
        call_stage: str,
        episode: DiagnosisEpisode | None = None,
        knowledge_case_ids: tuple[str, ...] = (),
        source_snapshot: list[dict] | None = None,
    ):
        self.db = db
        self.diagnosis = diagnosis
        self.settings = settings
        self.call_stage = call_stage
        self.episode = episode
        self.knowledge_case_ids = knowledge_case_ids
        self.reservations: list[AIUsageReservation] = []
        self._knowledge_snapshot = None
        self.source_snapshot = source_snapshot

    def _check_knowledge(self):
        from app.models.knowledge import KnowledgeCase
        from app.services.experiment_packages import load_experiment_package_runtime
        from app.services.memory import approved_case, case_source, package_source

        if self.source_snapshot is not None:
            from app.services.memory import current_source

            if not all(current_source(self.db, source, is_test_data=self.diagnosis.is_test_data)
                       for source in self.source_snapshot):
                raise AIQuotaDenied("AI_KNOWLEDGE_CHANGED")
        if self.diagnosis.experiment_version_id:
            snapshot = [package_source(load_experiment_package_runtime(
                self.db, self.diagnosis.experiment_version_id).version)]
        else:
            snapshot = []
            for case_id in sorted(self.knowledge_case_ids):
                case = self.db.get(KnowledgeCase, case_id, populate_existing=True)
                if not approved_case(case, is_test_data=self.diagnosis.is_test_data):
                    raise AIQuotaDenied("AI_KNOWLEDGE_WITHDRAWN")
                snapshot.append(case_source(case))
        if self._knowledge_snapshot is not None and snapshot != self._knowledge_snapshot:
            raise AIQuotaDenied("AI_KNOWLEDGE_CHANGED")
        self._knowledge_snapshot = snapshot

    @property
    def attempts(self) -> int:
        return len(self.reservations)

    @property
    def estimated_cost(self) -> float | None:
        costs = [item.accounted_cost for item in self.reservations]
        return sum(costs) if costs and all(item is not None for item in costs) else None

    def _reserve(self, client: AIClient, system_prompt: str, user_prompt: str):
        settings = self.settings
        if not settings.ai_enabled or not client.configured:
            raise AIQuotaDenied("AI_NOT_CONFIGURED")
        tokens = estimate_prompt_tokens(system_prompt, user_prompt)
        if tokens > settings.ai_input_token_limit:
            raise AIQuotaDenied("INPUT_TOKEN_LIMIT")
        projected = estimate_ai_cost(tokens, settings.ai_output_token_limit, settings)
        with _reservation_lock:
            # Existing business rows must be durable before reserving and sending.
            try:
                self.db.commit()
                dialect = self.db.get_bind().dialect.name
                if dialect == "postgresql":
                    self.db.execute(text("SELECT pg_advisory_xact_lock(873421, 91728)"))
                elif dialect == "sqlite":
                    self.db.connection().exec_driver_sql("BEGIN IMMEDIATE")
                else:
                    raise AIQuotaDenied("AI_QUOTA_STORAGE_UNSUPPORTED")
                if self.episode is None:
                    self.episode = episode_for_diagnosis(self.db, self.diagnosis)
                if self.episode is not None:
                    # expire_on_commit=False sessions may retain a pre-lock count.
                    self.db.refresh(self.episode)
                if self.episode is None and self.diagnosis.matched_rules:
                    raise AIQuotaDenied("EPISODE_SCOPE_UNRESOLVED")
                episodes = {
                    link.episode_id: link.episode for link in issue_links(self.db, self.diagnosis)
                }
                if self.episode:
                    episodes[self.episode.id] = self.episode
                for target in list(episodes.values()) or [None]:
                    if target:
                        self.db.refresh(target)
                    allowed, reason = budget_allowed(
                        self.db,
                        self.diagnosis.device_id,
                        settings,
                        target,
                        projected_call_cost=projected,
                    )
                    if not allowed:
                        raise AIQuotaDenied(reason or "AI_BUDGET_LIMIT")
                if projected is None and (
                    settings.ai_daily_budget is not None
                    or settings.ai_max_cost_per_call is not None
                ):
                    raise AIQuotaDenied("AI_COST_ESTIMATE_UNAVAILABLE")
                reservation = AIUsageReservation(
                    diagnosis_result_id=self.diagnosis.id,
                    device_id=self.diagnosis.device_id,
                    episode_id=self.episode.id if self.episode else None,
                    call_stage=self.call_stage,
                    provider=client.provider,
                    model=client.model,
                    status="reserved",
                    reserved_cost=projected,
                    accounted_cost=projected,
                    attribution={
                        "episode_ids": sorted(episodes),
                        "currency": settings.ai_budget_currency,
                        "price_version": settings.ai_price_version,
                        "day_timezone": "UTC",
                        "enforcement": "estimated_preflight",
                        "input_cost_per_1k": settings.ai_input_cost_per_1k_tokens,
                        "output_cost_per_1k": settings.ai_output_cost_per_1k_tokens,
                    },
                    is_test_data=self.diagnosis.is_test_data,
                )
                self.db.add(reservation)
                for target in episodes.values():
                    target.ai_call_count += 1
                self.db.commit()
                self.reservations.append(reservation)
                return reservation
            except AIQuotaDenied:
                self.db.rollback()
                raise
            except Exception as exc:
                self.db.rollback()
                raise AIQuotaDenied("AI_QUOTA_STORAGE_UNAVAILABLE") from exc

    def _settle(self):
        try:
            self.db.commit()
        except Exception as exc:
            self.db.rollback()
            # The pre-I/O reservation remains durable and charged. Never retry a
            # provider request just because its settlement could not be saved.
            raise AIQuotaDenied("AI_QUOTA_STORAGE_UNAVAILABLE") from exc

    def complete_json(
        self,
        client: AIClient,
        *,
        system_prompt: str,
        user_prompt: str,
    ) -> AICompletion:
        delivery_scope = current_delivery_scope(self.db, self.diagnosis)
        self._check_knowledge()
        reservation = self._reserve(client, system_prompt, user_prompt)
        try:
            # No hidden transport retries: each physical request needs a reservation.
            call = getattr(client, "complete_json_once", client.complete_json)
            completion = call(system_prompt=system_prompt, user_prompt=user_prompt)
        except Exception as exc:
            reservation.status = "failed"
            reservation.error_code = type(exc).__name__[:100]
            # A timeout does not prove that the provider did not process the request.
            self._settle()
            message = str(exc).lower()
            summary = (
                "AI Provider timeout"
                if "timeout" in message or "timed out" in message
                else "AI Provider attempt failed"
            )
            raise AIProviderError(summary) from exc
        reservation.status = "succeeded"
        reservation.input_tokens = completion.input_tokens
        reservation.output_tokens = completion.output_tokens
        if completion.input_tokens is not None and completion.output_tokens is not None:
            reservation.accounted_cost = estimate_ai_cost(
                completion.input_tokens, completion.output_tokens, self.settings
            )
        self._settle()
        self._check_knowledge()
        if current_delivery_scope(self.db, self.diagnosis) != delivery_scope:
            raise AIQuotaDenied("AI_RESULT_STALE")
        return completion
