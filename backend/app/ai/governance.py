"""Shared outbound gate. Reserve durably before I/O; never refund an uncertain request."""

from __future__ import annotations

import hashlib
import json
import threading
import time
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, text, update
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.ai.clients import AIClient, AICompletion, AIProviderError
from app.core.config import Settings
from app.models.ai_operation import AIOperation
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
        super().__init__(code, code=code, outcome_unknown=False)


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
        operation_key: str | None = None,
        execution_context: dict | None = None,
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
        self.operation_key = operation_key or f"diagnosis:{diagnosis.id}:{call_stage}"
        self.execution_context = execution_context or {}
        self.operation = None
        self.deadline = time.monotonic() + settings.ai_total_timeout_seconds

    @staticmethod
    def _aware(value):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)

    def retry(self, exc: Exception) -> bool:
        """One policy for all callers; unknown requests never retry."""
        if isinstance(exc, AIQuotaDenied):
            return False
        if isinstance(exc, AIProviderError):
            return exc.retryable and not exc.outcome_unknown
        # A completed, bounded response failed output validation. Its attempt is
        # charged; permit another physical attempt only within this operation.
        if self.operation is None or self.operation.status != "succeeded":
            return False
        try:
            changed = self.db.execute(
                update(AIOperation)
                .where(
                    AIOperation.id == self.operation.id,
                    AIOperation.status == "succeeded",
                    AIOperation.attempt_no == self.operation.attempt_no,
                )
                .values(
                    status="failed_known",
                    retry_allowed=True,
                    error_code="OUTPUT_INVALID",
                    completion=None,
                )
            ).rowcount
            self.db.commit()
            return bool(changed)
        except SQLAlchemyError as error:
            self.db.rollback()
            raise AIQuotaDenied("AI_QUOTA_STORAGE_UNAVAILABLE") from error

    def _wait_retry(self):
        operation = self.db.scalar(
            select(AIOperation).where(AIOperation.operation_key == self.operation_key)
        )
        if operation is None:
            return
        remaining = (
            self._aware(operation.deadline_at) - datetime.now(timezone.utc)
        ).total_seconds()
        self.deadline = min(self.deadline, time.monotonic() + remaining)
        if operation.status == "failed_known" and operation.retry_allowed:
            delay = (
                max(
                    0.0,
                    (self._aware(operation.retry_at) - datetime.now(timezone.utc)).total_seconds(),
                )
                if operation.retry_at
                else 0.0
            )
            if delay >= remaining or time.monotonic() + delay >= self.deadline:
                raise AIQuotaDenied("AI_DEADLINE_EXCEEDED")
            self.db.commit()  # no DB transaction during backoff
            if delay:
                time.sleep(delay)

    def _check_knowledge(self):
        from app.models.knowledge import KnowledgeCase
        from app.services.experiment_packages import load_experiment_package_runtime
        from app.services.memory import approved_case, case_source, package_source

        if self.source_snapshot is not None:
            from app.services.memory import current_source

            if not all(
                current_source(self.db, source, is_test_data=self.diagnosis.is_test_data)
                for source in self.source_snapshot
            ):
                raise AIQuotaDenied("AI_KNOWLEDGE_CHANGED")
        if self.diagnosis.experiment_version_id:
            snapshot = [
                package_source(
                    load_experiment_package_runtime(
                        self.db, self.diagnosis.experiment_version_id
                    ).version
                )
            ]
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
                from app.ai.context_contract import CONTEXT_POLICY_VERSION
                from app.ai.output_contract import (
                    OUTPUT_CONTRACT_VERSION,
                    REASONING_PROJECTION_VERSION,
                )

                versions = {
                    "provider": client.provider,
                    "model": client.model,
                    "schema": settings.ai_schema_version,
                    "prompt": settings.ai_prompt_version,
                    "contract": "ai-operation-v1",
                    "context_policy": CONTEXT_POLICY_VERSION,
                    "output_contract": OUTPUT_CONTRACT_VERSION,
                    "reasoning_projection": REASONING_PROJECTION_VERSION,
                    "entry_context": self.execution_context,
                    "max_attempts": settings.ai_max_retries + 1,
                    "total_timeout_seconds": settings.ai_total_timeout_seconds,
                    "response_max_bytes": settings.ai_response_max_bytes,
                    "output_token_limit": settings.ai_output_token_limit,
                }
                fingerprint = hashlib.sha256(
                    json.dumps(
                        [system_prompt, user_prompt, versions],
                        sort_keys=True,
                    ).encode()
                ).hexdigest()
                operation = self.db.scalar(
                    select(AIOperation)
                    .where(AIOperation.operation_key == self.operation_key)
                    .with_for_update()
                    .execution_options(populate_existing=True)
                )
                if operation is None:
                    legacy = self.db.scalar(
                        select(AIUsageReservation.id)
                        .where(
                            AIUsageReservation.diagnosis_result_id == self.diagnosis.id,
                            AIUsageReservation.call_stage == self.call_stage,
                            AIUsageReservation.operation_id.is_(None),
                        )
                        .limit(1)
                    )
                    if legacy:
                        raise AIQuotaDenied("AI_LEGACY_OUTCOME_UNRESOLVED")
                    operation = AIOperation(
                        operation_key=self.operation_key,
                        diagnosis_result_id=self.diagnosis.id,
                        call_stage=self.call_stage,
                        input_hash=fingerprint,
                        execution_versions=versions,
                        status="prepared",
                        attempt_no=0,
                        deadline_at=datetime.now(timezone.utc)
                        + timedelta(seconds=max(0, self.deadline - time.monotonic())),
                    )
                    self.db.add(operation)
                    self.db.flush()
                self.operation = operation
                if operation.input_hash != fingerprint:
                    raise AIQuotaDenied("AI_OPERATION_INPUT_CONFLICT")
                if operation.status == "succeeded" and operation.completion:
                    self.reservations = list(
                        self.db.scalars(
                            select(AIUsageReservation).where(
                                AIUsageReservation.operation_id == operation.id
                            )
                        )
                    )
                    self.db.commit()
                    return None
                if operation.status in {"dispatching", "outcome_unknown"}:
                    raise AIQuotaDenied("AI_OUTCOME_UNKNOWN")
                if operation.status == "failed_known" and not operation.retry_allowed:
                    raise AIQuotaDenied("AI_OPERATION_FAILED")
                if operation.attempt_no >= settings.ai_max_retries + 1:
                    raise AIQuotaDenied("AI_OPERATION_ATTEMPTS_EXHAUSTED")
                if (
                    self._aware(operation.deadline_at) <= datetime.now(timezone.utc)
                    or time.monotonic() >= self.deadline
                ):
                    raise AIQuotaDenied("AI_DEADLINE_EXCEEDED")
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
                    operation_id=operation.id,
                    attempt_no=operation.attempt_no + 1,
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
                operation.status = "dispatching"
                operation.attempt_no += 1
                operation.retry_allowed = False
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
        try:
            self._wait_retry()
        except SQLAlchemyError as exc:
            self.db.rollback()
            raise AIQuotaDenied("AI_QUOTA_STORAGE_UNAVAILABLE") from exc
        reservation = self._reserve(client, system_prompt, user_prompt)
        if reservation is None:
            return AICompletion(**self.operation.completion)
        try:
            call = getattr(client, "complete_json_once", client.complete_json)
            from app.ai.clients import OpenAICompatibleClient

            kwargs = {"system_prompt": system_prompt, "user_prompt": user_prompt}
            if isinstance(client, OpenAICompatibleClient):
                kwargs["timeout_seconds"] = max(0.001, self.deadline - time.monotonic())
            completion = call(**kwargs)
        except Exception as exc:
            safe = (
                exc
                if isinstance(exc, AIProviderError)
                else AIProviderError("AI Provider outcome unknown", code="OUTCOME_UNKNOWN")
            )
            reservation.status = "failed"
            reservation.error_code = safe.code
            self.operation.status = "outcome_unknown" if safe.outcome_unknown else "failed_known"
            self.operation.error_code = safe.code
            self.operation.retry_allowed = safe.retryable and not safe.outcome_unknown
            if self.operation.retry_allowed:
                delay = (
                    safe.retry_after
                    if safe.retry_after is not None
                    else min(0.25 * 2 ** (self.operation.attempt_no - 1), 2.0)
                )
                self.operation.retry_at = datetime.now(timezone.utc) + timedelta(seconds=delay)
            self._settle()
            raise safe from exc
        reservation.status = "succeeded"
        reservation.input_tokens = completion.input_tokens
        reservation.output_tokens = completion.output_tokens
        if completion.input_tokens is not None and completion.output_tokens is not None:
            reservation.accounted_cost = estimate_ai_cost(
                completion.input_tokens, completion.output_tokens, self.settings
            )
        self.operation.status = "succeeded"
        self.operation.completion = {
            "content": completion.content,
            "input_tokens": completion.input_tokens,
            "output_tokens": completion.output_tokens,
        }
        self.operation.retry_allowed = False
        self._settle()
        self._check_knowledge()
        if current_delivery_scope(self.db, self.diagnosis) != delivery_scope:
            raise AIQuotaDenied("AI_RESULT_STALE")
        return completion
