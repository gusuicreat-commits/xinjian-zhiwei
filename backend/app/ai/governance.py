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
from app.services.diagnosis_episode import episode_for_diagnosis
from app.services.lightweight_diagnosis import budget_allowed, estimate_ai_cost

# PostgreSQL also locks across workers. The process lock supports SQLite's
# single-connection in-memory test mode; file SQLite additionally locks writes.
_reservation_lock = threading.RLock()


class AIQuotaDenied(AIProviderError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def estimate_prompt_tokens(system_prompt: str, user_prompt: str) -> int:
    """Provider-independent estimate, including instructions and Schema, not only data.

    Compatible providers do not share a tokenizer. Actual usage is recorded on
    completion; this estimate is a preflight guard, not a claim of exact tokenization.
    """
    return max(1, (len((system_prompt + user_prompt).encode("utf-8")) + 2) // 3)


class GovernedAIInvocation:
    def __init__(
        self, db: Session, diagnosis: DiagnosisResult, settings: Settings,
        *, call_stage: str, episode: DiagnosisEpisode | None = None,
    ):
        self.db = db
        self.diagnosis = diagnosis
        self.settings = settings
        self.call_stage = call_stage
        self.episode = episode
        self.reservations: list[AIUsageReservation] = []

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
                allowed, reason = budget_allowed(
                    self.db, self.diagnosis.device_id, settings, self.episode,
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
                    call_stage=self.call_stage, provider=client.provider, model=client.model,
                    status="reserved", reserved_cost=projected, accounted_cost=projected,
                    is_test_data=self.diagnosis.is_test_data,
                )
                self.db.add(reservation)
                if self.episode is not None:
                    self.episode.ai_call_count += 1
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
        self, client: AIClient, *, system_prompt: str, user_prompt: str,
    ) -> AICompletion:
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
        return completion
