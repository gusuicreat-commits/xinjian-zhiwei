"""Shared outbound gate. Reserve durably before I/O; never refund an uncertain request."""

from __future__ import annotations

import hashlib
import json
import logging
import math
import threading
import time
from collections.abc import Callable
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, inspect, select, text, update
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.ai.clients import (
    AIClient,
    AICompletion,
    AIProviderError,
    ProviderOutcomeUnknown,
    classified_provider_error,
)
from app.core.config import Settings
from app.core.errors import (
    AccessDenied,
    ConflictError,
    InvalidRequest,
    StaleError,
    TemporarilyUnavailable,
)
from app.models.ai_operation import AIOperation
from app.models.ai_usage_reservation import AIUsageReservation
from app.models.base import utc_now
from app.models.classroom import AuditEvent
from app.models.diagnosis_episode import DiagnosisEpisode
from app.models.diagnosis_result import DiagnosisResult
from app.services.auth import AuthorizationDenied
from app.services.data_scope import ScopeViolation
from app.services.diagnosis_episode import episode_for_diagnosis, issue_links
from app.services.lightweight_diagnosis import budget_allowed, estimate_ai_cost

# PostgreSQL also locks across workers. The process lock supports SQLite's
# single-connection in-memory test mode; file SQLite additionally locks writes.
_reservation_lock = threading.RLock()
logger = logging.getLogger(__name__)


class AIQuotaDenied(AIProviderError):
    """Compatibility base; refusals and storage failures have distinct subclasses."""
    def __init__(self, code: str):
        super().__init__(code, code=code, outcome_unknown=False)


class AIQuotaRejected(AIQuotaDenied, ConflictError):
    """Definite gate/budget/state refusal; no new physical attempt admitted."""


class AIInputRejected(AIQuotaDenied, InvalidRequest):
    """Definite preflight input/configuration refusal."""


class AIScopeRejected(AIQuotaDenied, AccessDenied):
    """Definite teaching/source scope refusal; storage failure is separate."""

    def __init__(self, code):
        super().__init__(code)
        self.status_code = 403


class AIResultStale(AIQuotaDenied, StaleError):
    """The source/version is known to have changed."""


class AIStorageUnavailable(AIQuotaDenied, TemporarilyUnavailable):
    """Storage unavailable; retain durable reservations and never authorize resend."""


class AIOutcomeUnknown(AIQuotaDenied, ProviderOutcomeUnknown):
    """Compatibility refusal when recovering an unresolved/dispatching operation."""

    def __init__(self, code):
        AIProviderError.__init__(self, code, code=code, outcome_unknown=True)


@dataclass(frozen=True)
class TaskAttemptLimits:
    """Optional isolated-task limits, persisted with the existing operation contract.

    A task owns a dedicated diagnosis. Once bound, later stages inherit the strictest
    persisted limits even if their caller omits this argument. No separate cost ledger.
    """
    total: int = 5
    selection: int = 3

    def __post_init__(self):
        if type(self.total) is not int or not 0 <= self.total <= 5:
            raise ValueError("invalid total attempt limit")
        if type(self.selection) is not int or not 0 <= self.selection <= 3:
            raise ValueError("invalid selection attempt limit")


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
            raise AIScopeRejected("EPISODE_SCOPE_UNRESOLVED")
        owner = diagnosis_session(db, diagnosis)
        if (diagnosis.context_snapshot or {}).get("feedback_scope") and owner is None:
            raise AIScopeRejected("AI_DIAGNOSIS_OWNER_UNRESOLVED")
        if owner is not None:
            db.refresh(owner)
            student = db.get(User, owner.student_user_id, populate_existing=True)
            if student is None or not student.is_active or owner.status != "active":
                raise AIScopeRejected("AI_SESSION_SCOPE_DENIED")
            if not is_demo_session(db, owner):
                assert_student_session_access(db, student, owner)
        if diagnosis.experiment_version_id:
            load_experiment_package_runtime(db, diagnosis.experiment_version_id)
        from app.services.memory import diagnosis_sources_available

        if not diagnosis_sources_available(db, diagnosis):
            raise AIScopeRejected("AI_KNOWLEDGE_WITHDRAWN")
        result = []
        for link in issue_links(db, diagnosis):
            db.refresh(link.episode)
            result.append((link.episode_id, link.episode.status, link.episode.evidence_revision))
        return tuple(sorted(result))
    except AIQuotaDenied:
        raise
    except (AuthorizationDenied, ScopeViolation):
        raise
    except SQLAlchemyError as exc:
        if getattr(getattr(exc, "orig", None), "sqlstate", None) in {"55P03", "57014"}:
            raise AIStorageUnavailable("AI_DEADLINE_EXCEEDED") from exc
        raise AIStorageUnavailable("AI_TEACHING_SCOPE_UNAVAILABLE") from exc


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
        recheck_access: Callable[[], None] | None = None,
        task_attempt_limits: TaskAttemptLimits | None = None,
        cumulative_budget_limit: float | None = None,
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
        # Runtime-only authority; never serialize identities into an operation.
        self.recheck_access = recheck_access
        self.task_attempt_limits = task_attempt_limits
        if cumulative_budget_limit is not None and (
            isinstance(cumulative_budget_limit, bool)
            or not math.isfinite(cumulative_budget_limit) or cumulative_budget_limit < 0
        ):
            raise ValueError("invalid cumulative budget")
        # Optional isolated-ledger ceiling: all reservations, no rolling-day reset.
        self.cumulative_budget_limit = cumulative_budget_limit
        self._delivery_scope = None
        self.operation = None
        self.completion_available_for_delivery = False
        self.deadline = time.monotonic() + settings.ai_total_timeout_seconds

    def audit_delivery_denial(self, error_code: str) -> bool:
        """Link a refused delivery to its paid operation, without copying content or cost.

        The operation row serializes writers across PostgreSQL workers; the process
        lock also protects single-connection SQLite fixtures. Roll back any draft
        mutation before persisting this independent event. Audit failure must never
        replace the caller's authorization refusal or permit delivery.
        """
        if not self.completion_available_for_delivery or self.operation is None:
            return False
        # A final write refusal can expire the ORM object. Its persistent identity
        # avoids an unaudited SELECT before the storage-error handler is active.
        identity = inspect(self.operation).identity
        if identity is None:
            return False
        operation_id = identity[0]
        try:
            self.db.rollback()
        except SQLAlchemyError:
            logger.error("ai_delivery_denial_audit_unavailable")
            return False
        if not _reservation_lock.acquire(timeout=2):
            logger.error("ai_delivery_denial_audit_unavailable")
            return False
        try:
            if self.db.get_bind().dialect.name == "postgresql":
                self.db.execute(text(
                    "SELECT set_config('lock_timeout', '2000', true), "
                    "set_config('statement_timeout', '2000', true)"
                ))
            operation = self.db.scalar(select(AIOperation).where(
                AIOperation.id == operation_id
            ).with_for_update().execution_options(populate_existing=True))
            if operation is None or operation.status != "succeeded":
                self.db.rollback()
                return False
            existing = self.db.scalar(select(AuditEvent.id).where(
                AuditEvent.action == "ai.delivery_denied",
                AuditEvent.resource_type == "ai_operation",
                AuditEvent.resource_id == operation.id,
            ))
            if existing is None:
                self.db.add(AuditEvent(
                    action="ai.delivery_denied",
                    resource_type="ai_operation",
                    resource_id=operation.id,
                    details_json={"call_stage": operation.call_stage,
                                  "attempt_no": operation.attempt_no,
                                  "error_code": error_code},
                    is_test_data=self.diagnosis.is_test_data,
                    created_at=utc_now(),
                ))
            self.db.commit()
            return True
        except SQLAlchemyError:
            try:
                self.db.rollback()
            except SQLAlchemyError:
                # Best-effort audit cleanup cannot replace the delivery refusal.
                pass
            logger.error("ai_delivery_denial_audit_unavailable")
            return False
        finally:
            _reservation_lock.release()

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
            raise AIStorageUnavailable("AI_QUOTA_STORAGE_UNAVAILABLE") from error

    def _wait_retry(self):
        operation = self.db.scalar(
            select(AIOperation).where(AIOperation.operation_key == self.operation_key)
        )
        if operation is None:
            return
        if operation.status == "succeeded" and operation.completion:
            # A completed operation can be read after its dispatch deadline.
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
                raise AIQuotaRejected("AI_DEADLINE_EXCEEDED")
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
                raise AIResultStale("AI_KNOWLEDGE_CHANGED")
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
                    raise AIScopeRejected("AI_KNOWLEDGE_WITHDRAWN")
                snapshot.append(case_source(case))
        if self._knowledge_snapshot is not None and snapshot != self._knowledge_snapshot:
            raise AIResultStale("AI_KNOWLEDGE_CHANGED")
        self._knowledge_snapshot = snapshot

    @property
    def attempts(self) -> int:
        return len(self.reservations)

    @property
    def estimated_cost(self) -> float | None:
        costs = [item.accounted_cost for item in self.reservations]
        return sum(costs) if costs and all(item is not None for item in costs) else None

    def _bound_database_wait(self):
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            raise AIQuotaRejected("AI_DEADLINE_EXCEEDED")
        if self.db.get_bind().dialect.name == "postgresql":
            # Transaction-local: pool reuse must not inherit this request's limit.
            millis = str(max(1, int(remaining * 1000)))
            self.db.execute(text(
                "SELECT set_config('lock_timeout', :millis, true), "
                "set_config('statement_timeout', :millis, true)"
            ), {"millis": millis})

    @contextmanager
    def _reservation_slot(self):
        remaining = max(0.0, self.deadline - time.monotonic())
        if not _reservation_lock.acquire(timeout=remaining):
            raise AIQuotaRejected("AI_DEADLINE_EXCEEDED")
        try:
            yield
        finally:
            _reservation_lock.release()

    @staticmethod
    def _storage_error(exc):
        code = getattr(getattr(exc, "orig", None), "sqlstate", None)
        return AIStorageUnavailable(
            "AI_DEADLINE_EXCEEDED" if code in {"55P03", "57014"}
            else "AI_QUOTA_STORAGE_UNAVAILABLE"
        )

    def _reserve(self, client: AIClient, system_prompt: str, user_prompt: str):
        settings = self.settings
        if not settings.ai_enabled or not client.configured:
            raise AIInputRejected("AI_NOT_CONFIGURED")
        tokens = estimate_prompt_tokens(system_prompt, user_prompt)
        if tokens > settings.ai_input_token_limit:
            raise AIInputRejected("INPUT_TOKEN_LIMIT")
        projected = estimate_ai_cost(tokens, settings.ai_output_token_limit, settings)
        with self._reservation_slot():
            # Existing business rows must be durable before reserving and sending.
            try:
                self.db.commit()
                self._bound_database_wait()
                dialect = self.db.get_bind().dialect.name
                if dialect == "postgresql":
                    self.db.execute(text("SELECT pg_advisory_xact_lock(873421, 91728)"))
                elif dialect == "sqlite":
                    self.db.connection().exec_driver_sql("BEGIN IMMEDIATE")
                else:
                    raise AIInputRejected("AI_QUOTA_STORAGE_UNSUPPORTED")
                # Both backoff and quota-lock acquisition can outlive authority.
                # Validate before *either* a new reservation or a saved completion.
                if self.recheck_access is not None:
                    self.recheck_access()
                if current_delivery_scope(self.db, self.diagnosis) != self._delivery_scope:
                    raise AIResultStale("AI_RESULT_STALE")
                self._check_knowledge()
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
                # Under the existing cross-process quota lock, inherit the strictest
                # task contract for this dedicated diagnosis across all stages.
                limits = [self.task_attempt_limits] if self.task_attempt_limits else []
                budgets = ([self.cumulative_budget_limit]
                           if self.cumulative_budget_limit is not None else [])
                for saved in self.db.scalars(select(AIOperation.execution_versions).where(
                    AIOperation.diagnosis_result_id == self.diagnosis.id
                )):
                    if saved.get("cumulative_budget_limit") is not None:
                        budgets.append(saved["cumulative_budget_limit"])
                    if saved.get("task_attempt_limits") is not None:
                        limits.append(TaskAttemptLimits(**saved["task_attempt_limits"]))
                effective_limits = (TaskAttemptLimits(
                    total=min(v.total for v in limits),
                    selection=min(v.selection for v in limits),
                ) if limits else None)
                if effective_limits is not None:
                    versions["task_attempt_limits"] = asdict(effective_limits)
                effective_budget = min(budgets) if budgets else None
                if effective_budget is not None:
                    versions["cumulative_budget_limit"] = effective_budget
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
                        raise AIOutcomeUnknown("AI_LEGACY_OUTCOME_UNRESOLVED")
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
                    raise AIQuotaRejected("AI_OPERATION_INPUT_CONFLICT")
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
                    raise AIOutcomeUnknown("AI_OUTCOME_UNKNOWN")
                if operation.status == "failed_known" and not operation.retry_allowed:
                    raise AIQuotaRejected("AI_OPERATION_FAILED")
                if operation.attempt_no >= settings.ai_max_retries + 1:
                    raise AIQuotaRejected("AI_OPERATION_ATTEMPTS_EXHAUSTED")
                if (
                    self._aware(operation.deadline_at) <= datetime.now(timezone.utc)
                    or time.monotonic() >= self.deadline
                ):
                    raise AIQuotaRejected("AI_DEADLINE_EXCEEDED")
                if effective_limits is not None:
                    attempts = self.db.scalar(select(func.count(AIUsageReservation.id)).where(
                        AIUsageReservation.diagnosis_result_id == self.diagnosis.id
                    ))
                    selections = self.db.scalar(select(func.count(AIUsageReservation.id)).where(
                        AIUsageReservation.diagnosis_result_id == self.diagnosis.id,
                        AIUsageReservation.call_stage == "query_select",
                    ))
                    if attempts >= effective_limits.total:
                        raise AIQuotaRejected("AI_TASK_ATTEMPTS_EXHAUSTED")
                    if (self.call_stage == "query_select"
                            and selections >= effective_limits.selection):
                        raise AIQuotaRejected("AI_SELECTION_ATTEMPTS_EXHAUSTED")
                if effective_budget is not None:
                    # Under the same quota lock as reservation creation, count failed,
                    # in-flight and older-day calls. Do not introduce another ledger.
                    unknown_costs = self.db.scalar(select(func.count(AIUsageReservation.id)).where(
                        AIUsageReservation.accounted_cost.is_(None)
                    ))
                    spent = self.db.scalar(select(func.coalesce(
                        func.sum(AIUsageReservation.accounted_cost), 0.0
                    )))
                    if projected is None or unknown_costs:
                        raise AIQuotaRejected("AI_CUMULATIVE_COST_UNRESOLVED")
                    if float(spent) + projected > effective_budget:
                        raise AIQuotaRejected("AI_CUMULATIVE_BUDGET_LIMIT")
                if self.episode is None:
                    self.episode = episode_for_diagnosis(self.db, self.diagnosis)
                if self.episode is not None:
                    # expire_on_commit=False sessions may retain a pre-lock count.
                    self.db.refresh(self.episode)
                if self.episode is None and self.diagnosis.matched_rules:
                    raise AIScopeRejected("EPISODE_SCOPE_UNRESOLVED")
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
                        raise AIQuotaRejected(reason or "AI_BUDGET_LIMIT")
                if projected is None and (
                    settings.ai_daily_budget is not None
                    or settings.ai_max_cost_per_call is not None
                ):
                    raise AIInputRejected("AI_COST_ESTIMATE_UNAVAILABLE")
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
            except (AuthorizationDenied, ScopeViolation):
                self.db.rollback()
                raise
            except SQLAlchemyError as exc:
                self.db.rollback()
                raise self._storage_error(exc) from exc

    def _settle(self):
        try:
            self.db.commit()
        except SQLAlchemyError as exc:
            self.db.rollback()
            # The pre-I/O reservation remains durable and charged. Never retry a
            # provider request just because its settlement could not be saved.
            raise AIStorageUnavailable("AI_QUOTA_STORAGE_UNAVAILABLE") from exc

    def complete_json(
        self,
        client: AIClient,
        *,
        system_prompt: str,
        user_prompt: str,
    ) -> AICompletion:
        # A prior succeeded operation can be loaded during a new, conflicting request.
        # Only a response settled by this invocation may create a post-response audit.
        self.response_settled_this_call = False
        self.completion_available_for_delivery = False
        try:
            self._bound_database_wait()
            delivery_scope = current_delivery_scope(self.db, self.diagnosis)
            self._delivery_scope = delivery_scope
            self._check_knowledge()
            self._wait_retry()
        except AIQuotaDenied:
            self.db.rollback()
            raise
        except SQLAlchemyError as exc:
            self.db.rollback()
            raise self._storage_error(exc) from exc
        try:
            reservation = self._reserve(client, system_prompt, user_prompt)
        except AIQuotaDenied:
            self.db.rollback()
            raise
        if reservation is None:
            self.completion_available_for_delivery = True
            return AICompletion(**self.operation.completion)
        try:
            call = getattr(client, "complete_json_once", client.complete_json)
            from app.ai.clients import OpenAICompatibleClient

            kwargs = {"system_prompt": system_prompt, "user_prompt": user_prompt}
            if isinstance(client, OpenAICompatibleClient):
                kwargs["timeout_seconds"] = max(0.001, self.deadline - time.monotonic())
            completion = call(**kwargs)
        except AIProviderError as exc:
            safe = exc if isinstance(exc, AIQuotaDenied) else classified_provider_error(exc)
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
            if safe is exc:
                raise
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
        self.response_settled_this_call = True
        self.completion_available_for_delivery = True
        try:
            self._bound_database_wait()
            if self.recheck_access is not None:
                self.recheck_access()
            self._check_knowledge()
            if current_delivery_scope(self.db, self.diagnosis) != delivery_scope:
                raise AIResultStale("AI_RESULT_STALE")
        except AIQuotaDenied:
            self.db.rollback()
            raise
        except SQLAlchemyError as exc:
            self.db.rollback()
            raise self._storage_error(exc) from exc
        return completion
