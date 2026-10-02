from __future__ import annotations

import hashlib
import json
import time
from datetime import datetime, timedelta, timezone
from typing import Any

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.ai.clients import (
    AIClient,
    AIProviderError,
    build_ai_client,
)
from app.ai.context_builder import audit_manifest, prepare_explanation, selected_sources
from app.ai.context_contract import (
    CONTEXT_CONTRACT_VERSION,
    CONTEXT_POLICY_VERSION,
    ContextManifestV1,
)
from app.ai.context_sanitizer import (
    ProviderInputError,
    anonymous_device_id,
    audit_snapshot,
    build_safe_ai_input,
)
from app.ai.governance import (
    AIQuotaDenied,
    GovernedAIInvocation,
    current_delivery_scope,
    estimate_prompt_tokens,
)
from app.ai.output_contract import explanation_contract
from app.ai.schemas import (
    AIDiagnosisInput,
    AIExplanationResponse,
    AIKnowledgeReference,
    AIStatusResponse,
    AIStructuredExplanation,
)
from app.core.config import Settings
from app.knowledge.matcher import match_knowledge_case_definitions, match_knowledge_cases
from app.knowledge.projection import case_references
from app.models.ai_call_record import AICallRecord
from app.models.ai_explanation_cache import AIExplanationCache
from app.models.device import Device
from app.models.diagnosis_episode import DiagnosisEpisode
from app.models.diagnosis_result import DiagnosisResult
from app.models.guidance_history import GuidanceHistory
from app.services.diagnosis_episode import upsert_episode
from app.services.experiment_packages import load_experiment_package_runtime
from app.services.lightweight_diagnosis import (
    build_diagnosis_core,
    decide_ai_policy,
    explanation_fingerprint,
    render_deterministic_explanation,
)
from app.services.provenance import derive_test_flag


def get_ai_status(settings: Settings) -> AIStatusResponse:
    if not settings.ai_configured:
        notice = (
            "DeepSeek Provider 与模型已选定，但调用开关或服务端密钥未就绪；"
            "系统保持确定性规则诊断模式。"
        )
    else:
        notice = "DeepSeek 非思考模式已配置；调用仍受知识审核、隐私过滤、预算、缓存和结构校验保护。"
    return AIStatusResponse(
        provider_configured=settings.ai_configured,
        require_knowledge=settings.ai_require_knowledge,
        provider=settings.ai_provider,
        model=settings.ai_model,
        transport=settings.ai_transport,
        prompt_version=settings.ai_prompt_version,
        notice=notice,
        ai_enabled=settings.ai_enabled,
        local_configured=settings.local_ai_configured,
        cloud_configured=settings.cloud_ai_configured,
        thinking_enabled=settings.ai_thinking_enabled,
    )


def _build_input(
    record: DiagnosisResult,
    guidance: list[GuidanceHistory],
    knowledge: list[AIKnowledgeReference],
    settings: Settings,
    *,
    episode_id: str | None,
    user_question: str | None,
    workflow_state: dict[str, Any] | None,
) -> AIDiagnosisInput:
    return build_safe_ai_input(
        record,
        guidance,
        knowledge,
        settings,
        episode_id=episode_id,
        user_question=user_question,
        workflow_state=workflow_state,
    )


def _match_structured_knowledge(
    db: Session,
    record: DiagnosisResult,
    guidance: list[GuidanceHistory],
    settings: Settings,
) -> list[AIKnowledgeReference]:
    """Adapt deterministic structured-case matches for the governed AI input."""

    if record.experiment_version_id:
        package_runtime = load_experiment_package_runtime(db, record.experiment_version_id)
        cases = match_knowledge_case_definitions(
            record,
            guidance,
            package_runtime.bundle.cases.cases,
            limit=settings.ai_knowledge_limit,
        )
    else:
        cases = match_knowledge_cases(db, record, guidance, limit=settings.ai_knowledge_limit)
    return case_references(cases)


def _validate_explanation(raw_content: str, payload: AIDiagnosisInput) -> AIStructuredExplanation:
    document = json.loads(raw_content)
    explanation = AIStructuredExplanation.model_validate(document)
    allowed_errors = {
        str(match.get("error_type")) for match in payload.rule_matches if match.get("error_type")
    }
    if explanation.error_type not in allowed_errors:
        if allowed_errors or explanation.error_type != "UNCLASSIFIED_ANOMALY":
            raise ValueError("AI error_type must match a deterministic rule result")
    allowed_evidence = set(payload.allowed_evidence)
    if any(item not in allowed_evidence for item in explanation.evidence):
        raise ValueError("AI evidence must be selected from deterministic evidence")
    reasoned_causes = payload.workflow_state.get("reasoned_causes") or []
    allowed_cause_support = {
        str(item.get("cause")): str(item.get("support_level") or "unknown")
        for item in reasoned_causes
        if isinstance(item, dict) and item.get("cause")
    }
    # An explicit empty/unknown reasoning result is authoritative. Only legacy
    # callers without a reasoning stage may fall back to fault-tree candidates.
    if payload.workflow_state.get("reasoning_status") == "unknown":
        allowed_cause_support = {}
    allowed_causes = set(allowed_cause_support)
    if (
        "reasoning_status" not in payload.workflow_state
        and "reasoned_causes" not in payload.workflow_state
    ):
        allowed_causes = {
            str(cause.get("title"))
            for guidance in payload.fault_tree_guidance
            for cause in guidance.get("ranked_causes", [])
            if cause.get("title")
        }
    if any(item.cause not in allowed_causes for item in explanation.possible_causes):
        raise ValueError("AI explanation introduced a cause outside constrained reasoning")
    support_rank = {"unknown": 0, "low": 1, "medium": 2, "high": 3}
    if allowed_cause_support and any(
        support_rank[item.support_level] > support_rank[allowed_cause_support[item.cause]]
        for item in explanation.possible_causes
    ):
        raise ValueError("AI explanation increased a constrained support level")
    allowed_chunks = {item.chunk_id for item in payload.knowledge}
    referenced_chunks = {
        reference_id
        for cause in explanation.possible_causes
        for reference_id in [*cause.knowledge_case_ids, *cause.knowledge_chunk_ids]
    }
    if not referenced_chunks.issubset(allowed_chunks):
        raise ValueError("AI knowledge references must come from retrieved chunks")
    contract = explanation_contract(payload)
    if any(step not in contract["allowed_steps"] for step in explanation.steps):
        raise ValueError("AI explanation step must come from the allowed steps")
    if (
        any(cause.support_level == "high" for cause in explanation.possible_causes)
        and not explanation.evidence
    ):
        raise ValueError("high support requires evidence in the explanation")
    return explanation.model_copy(
        update={"summary": contract["summary"], "limitations": contract["limitations"]}
    )


def _safe_error_summary(error: Exception | None) -> str:
    if error is None:
        return "AI_PROVIDER_UNKNOWN_FAILURE"
    if isinstance(error, json.JSONDecodeError):
        return "AI_RESPONSE_INVALID_JSON"
    if isinstance(error, ValidationError):
        return "AI_RESPONSE_SCHEMA_VALIDATION_FAILED"
    message = str(error).lower()
    if "timeout" in message or "timed out" in message:
        return "AI_PROVIDER_TIMEOUT"
    if "rate" in message or "429" in message:
        return "AI_PROVIDER_RATE_LIMITED"
    if "auth" in message or "401" in message or "403" in message:
        return "AI_PROVIDER_AUTH_FAILED"
    if "balance" in message or "402" in message:
        return "AI_PROVIDER_BUDGET_UNAVAILABLE"
    if isinstance(error, AIProviderError):
        return "AI_PROVIDER_REQUEST_FAILED"
    return "AI_RESPONSE_VALIDATION_FAILED"


def _workflow_ai_record(
    db: Session,
    workflow_run_id: str | None,
    call_stage: str = "explanation",
) -> AICallRecord | None:
    if not workflow_run_id:
        return None
    return db.scalar(
        select(AICallRecord).where(
            AICallRecord.workflow_run_id == workflow_run_id,
            AICallRecord.call_stage == call_stage,
        )
    )


def _save_record(
    db: Session,
    *,
    diagnosis: DiagnosisResult,
    settings: Settings,
    payload: AIDiagnosisInput,
    prompt_hash: str,
    status: str,
    attempt_count: int,
    duration_ms: int,
    explanation: AIStructuredExplanation | None,
    knowledge: list[AIKnowledgeReference],
    input_tokens: int | None = None,
    output_tokens: int | None = None,
    error_code: str | None = None,
    error_message: str | None = None,
    episode: DiagnosisEpisode | None = None,
    trigger_reason: str | None = None,
    cache_status: str | None = None,
    route: str | None = None,
    route_path: str | None = None,
    validation_status: str | None = None,
    fallback_reason: str | None = None,
    estimated_cost: float | None = None,
    provider: str | None = None,
    model_name: str | None = None,
    transport: str | None = None,
    workflow_run_id: str | None = None,
    call_stage: str = "explanation",
    memory_sources: list[dict[str, Any]] | None = None,
) -> tuple[AICallRecord, bool]:
    existing = _workflow_ai_record(db, workflow_run_id, call_stage)
    if existing is not None:
        return existing, False
    record = AICallRecord(
        call_stage=call_stage,
        diagnosis_result_id=diagnosis.id,
        episode_id=episode.id if episode else None,
        workflow_run_id=workflow_run_id,
        provider=provider
        if provider is not None
        else settings.ai_provider
        if settings.ai_configured
        else None,
        model=model_name
        if model_name is not None
        else settings.ai_model
        if settings.ai_configured
        else None,
        transport=transport or settings.ai_transport,
        prompt_version=settings.ai_prompt_version,
        prompt_hash=prompt_hash,
        status=status,
        quota_managed=True,
        attempt_count=attempt_count,
        duration_ms=duration_ms,
        input_snapshot={
            **_audit_snapshot(payload),
            "output_contract": explanation_contract(payload),
            **({"context_manifest": audit_manifest(
                payload._context_manifest, attempts=attempt_count,
                cache_origin=payload._context_manifest.get("cache_origin"),
            )} if payload._context_manifest else {}),
        },
        output_json=explanation.model_dump(mode="json") if explanation else None,
        knowledge_references=[item.model_dump(mode="json") for item in knowledge],
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        trigger_reason=trigger_reason,
        cache_status=cache_status,
        route=route,
        route_path=route_path,
        estimated_cost=estimated_cost,
        latency_ms=duration_ms,
        validation_status=validation_status,
        fallback_reason=fallback_reason,
        error_code=error_code,
        error_message=error_message,
        is_test_data=derive_test_flag(
            diagnosis.is_test_data, *(item.is_test_data for item in knowledge),
        ),
    )
    db.add(record)
    try:
        db.flush()
        from app.services.memory import record_uses

        record_uses(db, diagnosis, knowledge, target_type="ai_call", target_id=record.id,
                    use_kind="matched", sources=memory_sources)
        provided_sources = payload._context_manifest.get("prepared_source_refs", [])
        if attempt_count or cache_status == "hit":
            record_uses(db, diagnosis, [], target_type="ai_call", target_id=record.id,
                        use_kind="provided" if attempt_count else "derived",
                        sources=provided_sources)
        if explanation and memory_sources:
            cited = {key for cause in explanation.possible_causes
                     for key in [*cause.knowledge_case_ids, *cause.knowledge_chunk_ids]}
            record_uses(db, diagnosis, [], target_type="ai_call", target_id=record.id,
                        use_kind="cited", sources=[source for source in memory_sources
                        if source["kind"] in {"case", "package_case"} and source["id"] in cited])
        db.commit()
    except IntegrityError:
        db.rollback()
        existing = _workflow_ai_record(db, workflow_run_id, call_stage)
        if existing is not None:
            return existing, False
        raise
    db.refresh(record)
    return record, True


def _audit_snapshot(payload: AIDiagnosisInput) -> dict[str, Any]:
    return audit_snapshot(payload)


def _response(
    record: AICallRecord,
    explanation: AIStructuredExplanation | None,
    knowledge: list[AIKnowledgeReference],
    settings: Settings,
    notice: str,
    *,
    enhancement_status: str | None = None,
    trigger_reason: str | None = None,
    route: str | None = None,
    route_path: str | None = None,
    deterministic_result: dict[str, Any] | None = None,
) -> AIExplanationResponse:
    from sqlalchemy.orm import object_session

    from app.services.current_advice import current_sources_available

    db = object_session(record)
    diagnosis = db.get(DiagnosisResult, record.diagnosis_result_id) if db is not None else None
    available = current_sources_available(db, diagnosis, knowledge)
    if not available:
        explanation, knowledge, deterministic_result = None, [], None
        notice = "引用资料已停用或无法核验，请联系教师。"
        enhancement_status = "failed_fallback"
    return AIExplanationResponse(
        call_record_id=record.id,
        diagnosis_result_id=record.diagnosis_result_id,
        status=record.status if available else "skipped",
        mode="ai_enhanced" if record.status == "succeeded" and available else "rules_only",
        provider_configured=settings.ai_configured,
        explanation=explanation,
        knowledge_references=knowledge,
        notice=notice,
        enhancement_status=enhancement_status
        or ("cloud_success" if record.status == "succeeded" else "skipped"),
        trigger_reason=trigger_reason or record.trigger_reason or "UNSPECIFIED",
        route=route or record.route or "none",
        route_path=route_path or record.route_path or "deterministic_only",
        deterministic_result=deterministic_result,
    )


def serialize_ai_call(record: AICallRecord, settings: Settings) -> AIExplanationResponse:
    from sqlalchemy.orm import object_session

    from app.services.current_advice import assess_current_advice

    assessment = assess_current_advice(object_session(record), record)
    explanation = assessment.explanation
    if record.status == "succeeded" and not assessment.eligible:
        return _response(
            record, None, [], settings,
            "历史解释或引用资料未通过当前校验，请查看确定性诊断结果。",
            enhancement_status="failed_fallback",
        ).model_copy(update={"status": "failed", "mode": "rules_only"})
    knowledge = [AIKnowledgeReference.model_validate(item) for item in record.knowledge_references]
    if record.status == "succeeded":
        notice = "此接口仅补充解释；确定性规则、证据和故障树结果保持不变。"
    elif record.status == "failed":
        notice = "AI 调用或输出校验失败，当前展示规则诊断结果。"
    elif record.error_code == "AI_NOT_CONFIGURED":
        notice = "AI Provider 未配置，当前仅展示确定性规则诊断。"
    elif record.error_code == "KNOWLEDGE_NOT_READY":
        notice = "尚无匹配且已审核的结构化知识案例，当前仅展示确定性诊断。"
    else:
        notice = "AI 调用已跳过，当前展示确定性规则诊断。"
    return _response(
        record,
        explanation,
        knowledge,
        settings,
        notice,
        enhancement_status=(
            "cache_hit"
            if record.cache_status == "hit"
            else "failed_fallback"
            if record.status == "failed"
            else "disabled"
            if record.error_code == "AI_NOT_CONFIGURED"
            else None
        ),
    )


def _authorize_projection(db, diagnosis, student_actor):
    # None is available only to the private offline construction primitive.
    if student_actor is None:
        return
    from app.services.auth import AuthorizationDenied
    from app.services.data_scope import diagnosis_session
    from app.services.student_authorization import authorize_student_actor

    authorize_student_actor(db, student_actor, diagnosis.device_id, student_actor.session_id)
    owner = diagnosis_session(db, diagnosis)
    if owner is None or owner.id != student_actor.session_id:
        raise AuthorizationDenied(403)


def explain_diagnosis(db, device, diagnosis, settings, *, student_actor, **kwargs):
    """Authorized delivery; actual call audit survives a later projection denial."""
    from app.services.auth import AuthorizationDenied
    from app.services.student_authorization import StudentActorContext

    if not isinstance(student_actor, StudentActorContext) or diagnosis.device_id != device.id:
        raise AuthorizationDenied(401)
    _authorize_projection(db, diagnosis, student_actor)
    db.commit()  # Identity locks never span provider I/O.
    response = _explain_diagnosis(
        db, device, diagnosis, settings, student_actor=student_actor, **kwargs,
    )
    _authorize_projection(db, diagnosis, student_actor)
    db.commit()  # Release delivery locks before the next graph node can wait.
    return response


def _skipped_response(
    db: Session,
    *,
    diagnosis: DiagnosisResult,
    settings: Settings,
    payload: AIDiagnosisInput,
    prompt_hash: str,
    knowledge: list[AIKnowledgeReference],
    episode: DiagnosisEpisode | None,
    trigger_reason: str,
    error_code: str,
    error_message: str | None,
    notice: str,
    deterministic_result: dict[str, Any],
    started: float,
    estimated_cost: float = 0.0,
    workflow_run_id: str | None = None,
    call_stage: str = "explanation",
    memory_sources: list[dict[str, Any]] | None = None,
    student_actor=None,
) -> AIExplanationResponse:
    route_path = (
        "ai_disabled → deterministic_only"
        if error_code == "AI_NOT_CONFIGURED"
        else f"{error_code.lower()} → deterministic_only"
    )
    saved, created = _save_record(
        db,
        diagnosis=diagnosis,
        settings=settings,
        payload=payload,
        prompt_hash=prompt_hash,
        status="skipped",
        attempt_count=0,
        duration_ms=int((time.monotonic() - started) * 1000),
        explanation=None,
        knowledge=knowledge,
        memory_sources=memory_sources,
        error_code=error_code,
        error_message=error_message,
        episode=episode,
        trigger_reason=trigger_reason,
        cache_status="not_checked",
        route="none",
        route_path=route_path,
        validation_status="not_run",
        estimated_cost=estimated_cost,
        workflow_run_id=workflow_run_id,
        call_stage=call_stage,
    )
    if not created:
        response = serialize_ai_call(saved, settings)
        response.status = "skipped"
        response.mode = "rules_only"
        response.explanation = None
        response.knowledge_references = []
        response.enhancement_status = "disabled" if error_code == "AI_NOT_CONFIGURED" else "skipped"
        response.notice = notice
        response.deterministic_result = deterministic_result
        return response
    enhancement_status = "disabled" if error_code == "AI_NOT_CONFIGURED" else "skipped"
    _authorize_projection(db, diagnosis, student_actor)
    diagnosis.ai_enhancement = {
        "status": enhancement_status,
        "trigger_reason": trigger_reason,
        "route": "none",
        "route_path": route_path,
        "cache_status": "not_checked",
        "call_record_id": saved.id,
    }
    db.commit()
    return _response(
        saved,
        None,
        knowledge,
        settings,
        notice,
        enhancement_status=enhancement_status,
        trigger_reason=trigger_reason,
        route_path=route_path,
        deterministic_result=deterministic_result,
    )


def _explain_diagnosis(
    db: Session,
    device: Device,
    diagnosis: DiagnosisResult,
    settings: Settings,
    *,
    student_actor=None,
    ai_client: AIClient | None = None,
    ai_clients: list[tuple[str, AIClient]] | None = None,
    user_question: str | None = None,
    workflow_state: dict[str, Any] | None = None,
    retrieved_knowledge: list[AIKnowledgeReference] | None = None,
    workflow_run_id: str | None = None,
    call_stage: str = "explanation",
    operation_request_id: str | None = None,
) -> AIExplanationResponse:
    started = time.monotonic()
    existing = _workflow_ai_record(db, workflow_run_id, call_stage)
    guidance = list(
        db.scalars(
            select(GuidanceHistory)
            .where(GuidanceHistory.diagnosis_result_id == diagnosis.id)
            .order_by(GuidanceHistory.fault_tree_id)
        )
    )
    client_transport = (
        "injected-test"
        if ai_client is not None or ai_clients is not None
        else settings.ai_transport
    )
    if ai_clients is not None:
        clients = list(ai_clients)
    elif ai_client is not None:
        injected_route = (
            settings.ai_provider
            if settings.ai_provider and settings.ai_provider != "unconfigured"
            else ai_client.provider
        )
        clients: list[tuple[str, AIClient]] = [(injected_route, ai_client)]
    else:
        production_client = build_ai_client(settings)
        if settings.production_ai_configured:
            default_route = settings.ai_provider or "provider"
        elif settings.local_ai_configured:
            default_route = "local"
        else:
            default_route = "cloud"
        clients = [(default_route, production_client)] if production_client.configured else []
    ai = clients[0][1] if clients else build_ai_client(settings)
    knowledge: list[AIKnowledgeReference] = list(retrieved_knowledge or [])
    retrieval_error: str | None = None
    if retrieved_knowledge is None:
        try:
            knowledge = _match_structured_knowledge(db, diagnosis, guidance, settings)
        except (AIProviderError, ValueError) as exc:
            retrieval_error = str(exc)
    from app.services.memory import sources_for_references

    memory_sources = sources_for_references(db, diagnosis, knowledge)
    core = build_diagnosis_core(diagnosis, guidance, [item.chunk_id for item in knowledge])
    deterministic = render_deterministic_explanation(core)
    _authorize_projection(db, diagnosis, student_actor)
    diagnosis.deterministic_core = core.model_dump(mode="json")
    diagnosis.deterministic_explanation = deterministic.model_dump(mode="json")
    if student_actor is None:
        episode = upsert_episode(db, device, diagnosis, guidance, settings)
    else:
        from app.services.diagnosis_episode import episode_for_diagnosis

        episode = episode_for_diagnosis(db, diagnosis)
        db.commit()
    policy = decide_ai_policy(core, settings, episode=episode, user_question=user_question)

    rejected_context = None

    def without_provider(code: str, notice: str) -> AIExplanationResponse:
        # Minimal local audit only: neither telemetry aggregation nor Provider
        # Schema construction is a prerequisite for a deterministic diagnosis.
        local = AIDiagnosisInput(
            diagnosis_result_id=diagnosis.id,
            episode_id=episode.id if episode else None,
            anonymous_device_id=anonymous_device_id(device.device_key),
            device_state={},
            logs=[],
            sensor_readings=[],
            heartbeats=[],
            fault_tree_guidance=[],
            knowledge=[],
            rule_matches=[
                {"rule_id": item.get("rule_id"), "error_type": item.get("error_type")}
                for item in diagnosis.matched_rules
            ],
            allowed_evidence=[],
            is_test_data=derive_test_flag(diagnosis.is_test_data),
        )
        if rejected_context is not None:
            local._context_manifest = audit_manifest(rejected_context)
            reason = ("source_changed" if "KNOWLEDGE" in code else
                      "scope_unavailable" if "SCOPE" in code or code == "AI_RESULT_STALE"
                      else "context_incomplete")
            local._context_manifest["reason_codes"] = list(dict.fromkeys([
                *local._context_manifest.get("reason_codes", []), reason,
            ]))
        return _skipped_response(
            db,
            diagnosis=diagnosis,
            settings=settings,
            payload=local,
            prompt_hash=hashlib.sha256(f"provider-not-called:{code}".encode()).hexdigest(),
            knowledge=[],
            episode=episode,
            trigger_reason=policy.reason,
            error_code=code,
            error_message=None,
            notice=notice,
            deterministic_result=deterministic.model_dump(mode="json"),
            started=started,
            workflow_run_id=workflow_run_id,
            call_stage=call_stage,
            student_actor=student_actor,
        )

    if not settings.ai_enabled or not ai.configured:
        return without_provider("AI_NOT_CONFIGURED", "AI 未启用或未配置，当前返回确定性诊断。")
    try:
        current_delivery_scope(db, diagnosis)
    except AIQuotaDenied as exc:
        # Do not reuse an old successful workflow/cache result after withdrawal.
        if existing is not None:
            response = serialize_ai_call(existing, settings)
            response.explanation = None
            response.status = "skipped"
            response.mode = "rules_only"
            response.enhancement_status = "skipped"
            response.knowledge_references = []
            response.deterministic_result = None
            response.notice = "当前权限、问题或实验包状态已变化，请刷新并联系教师。"
            return response
        return without_provider(exc.code, "当前教学范围不可用，未返回 AI 增强。")
    if existing is not None:
        previous_refs = {item.get("chunk_id") for item in existing.knowledge_references}
        if not previous_refs.issubset({item.chunk_id for item in knowledge}):
            return without_provider("AI_KNOWLEDGE_WITHDRAWN", "原引用知识已不适用，保留规则结果。")
        return serialize_ai_call(existing, settings)
    try:
        payload = _build_input(
            diagnosis,
            guidance,
            knowledge,
            settings,
            episode_id=episode.id if episode else None,
            user_question=user_question,
            workflow_state=workflow_state,
        )
        payload, system_prompt, user_prompt, prompt_hash = prepare_explanation(
            payload, settings, memory_sources,
        )
        rejected_context = payload._context_manifest
    except (ValueError, TypeError, KeyError) as exc:
        rejected_context = ContextManifestV1(
            stage="explanation", required_complete=False, reason_codes=["context_incomplete"],
        )
        return without_provider(
            exc.code if isinstance(exc, ProviderInputError) else "AI_INPUT_INVALID",
            "AI 输入未通过外发边界检查，当前返回确定性诊断。",
        )
    # Persist and return only the allowlisted/redacted representation produced by
    # the privacy boundary, never the original retrieved chunk objects.
    knowledge = list(payload.knowledge)
    fault_tree_version = guidance[0].fault_tree_version if guidance else None
    cache_fingerprint = explanation_fingerprint(
        core,
        prompt_version=settings.ai_prompt_version,
        schema_version=settings.ai_schema_version,
        ruleset_version=diagnosis.ruleset_version,
        fault_tree_version=fault_tree_version,
        knowledge_chunk_ids=[item.chunk_id for item in knowledge],
        output_language=settings.ai_output_language,
        user_question=user_question,
    )

    # Include both the actual prompt and the context selection contract.
    cache_fingerprint = hashlib.sha256(
        f"{cache_fingerprint}:{prompt_hash}:{CONTEXT_CONTRACT_VERSION}:"
        f"{CONTEXT_POLICY_VERSION}".encode()
    ).hexdigest()
    skip_code: str | None = None
    notice: str | None = None
    if retrieval_error:
        skip_code = "KNOWLEDGE_MATCH_FAILED"
        notice = "结构化知识匹配失败，已降级为确定性诊断；未调用 AI。"
    elif not policy.should_call:
        skip_code = policy.reason
        notice = "确定性结果已足够，本次无需调用 AI。"
    estimated_input_tokens = estimate_prompt_tokens(system_prompt, user_prompt)
    if not payload._context_manifest["required_complete"]:
        skip_code = "INPUT_TOKEN_LIMIT"
        notice = "必需上下文无法完整放入预算，当前保留确定性结果。"
    if skip_code:
        return _skipped_response(
            db,
            diagnosis=diagnosis,
            settings=settings,
            payload=payload,
            prompt_hash=prompt_hash,
            knowledge=knowledge,
            memory_sources=memory_sources,
            episode=episode,
            trigger_reason=policy.reason,
            error_code=skip_code,
            error_message=retrieval_error,
            notice=notice or "AI 调用已跳过。",
            deterministic_result=deterministic.model_dump(mode="json"),
            started=started,
            workflow_run_id=workflow_run_id,
            call_stage=call_stage,
            student_actor=student_actor,
        )

    now = datetime.now(timezone.utc)
    cached = db.scalar(
        select(AIExplanationCache).where(
            AIExplanationCache.fingerprint == cache_fingerprint,
            AIExplanationCache.expires_at > now,
        )
    )
    if cached is not None:
        from app.services.memory import current_source

        if not all(current_source(db, source, is_test_data=diagnosis.is_test_data)
                   for source in memory_sources):
            return without_provider("AI_KNOWLEDGE_CHANGED", "资料来源已变化，保留确定性结果。")
        try:
            current_delivery_scope(db, diagnosis)
        except AIQuotaDenied as exc:
            return without_provider(exc.code, "当前教学范围已变化，保留确定性结果。")
        try:
            explanation = _validate_explanation(json.dumps(cached.explanation_json), payload)
        except (ValueError, TypeError):
            db.delete(cached)  # Rebuildable cache, not an immutable audit record.
            db.flush()
            cached = None
    if cached is not None:
        payload._context_manifest["cache_origin"] = cache_fingerprint
        cached.hit_count += 1
        cached.last_hit_at = now
        saved, created = _save_record(
            db,
            diagnosis=diagnosis,
            settings=settings,
            payload=payload,
            prompt_hash=prompt_hash,
            status="succeeded",
            attempt_count=0,
            duration_ms=int((time.monotonic() - started) * 1000),
            explanation=explanation,
            knowledge=knowledge,
            memory_sources=memory_sources,
            episode=episode,
            trigger_reason=policy.reason,
            cache_status="hit",
            route="cache",
            route_path="cache_hit",
            validation_status="cache_valid",
            estimated_cost=0.0,
            provider=cached.provider,
            model_name=cached.model_name,
            transport="cache",
            workflow_run_id=workflow_run_id,
            call_stage=call_stage,
        )
        if not created:
            return serialize_ai_call(saved, settings)
        _authorize_projection(db, diagnosis, student_actor)
        diagnosis.ai_enhancement = {
            "status": "cache_hit",
            "trigger_reason": policy.reason,
            "route": "cache",
            "route_path": "cache_hit",
            "cache_status": "hit",
            "call_record_id": saved.id,
        }
        db.commit()
        return _response(
            saved,
            explanation,
            knowledge,
            settings,
            "复用了相同规则、知识版本和输入指纹的已校验解释。",
            enhancement_status="cache_hit",
            trigger_reason=policy.reason,
            route="cache",
            route_path="cache_hit",
            deterministic_result=deterministic.model_dump(mode="json"),
        )

    if not settings.ai_enabled or not ai.configured:
        return _skipped_response(
            db,
            diagnosis=diagnosis,
            settings=settings,
            payload=payload,
            prompt_hash=prompt_hash,
            knowledge=knowledge,
            memory_sources=memory_sources,
            episode=episode,
            trigger_reason=policy.reason,
            error_code="AI_NOT_CONFIGURED",
            error_message=None,
            notice="AI Provider 未配置，当前仅返回确定性规则和故障树结果。",
            deterministic_result=deterministic.model_dump(mode="json"),
            started=started,
            workflow_run_id=workflow_run_id,
            call_stage=call_stage,
            student_actor=student_actor,
        )

    if settings.ai_require_knowledge and not knowledge:
        return _skipped_response(
            db,
            diagnosis=diagnosis,
            settings=settings,
            payload=payload,
            prompt_hash=prompt_hash,
            knowledge=knowledge,
            memory_sources=memory_sources,
            episode=episode,
            trigger_reason=policy.reason,
            error_code="KNOWLEDGE_NOT_READY",
            error_message=None,
            notice="尚无可用的已审核结构化知识案例，已保持确定性诊断模式。",
            deterministic_result=deterministic.model_dump(mode="json"),
            started=started,
            workflow_run_id=workflow_run_id,
            call_stage=call_stage,
            student_actor=student_actor,
        )

    if estimated_input_tokens > settings.ai_input_token_limit:
        return _skipped_response(
            db,
            diagnosis=diagnosis,
            settings=settings,
            payload=payload,
            prompt_hash=prompt_hash,
            knowledge=knowledge,
            memory_sources=memory_sources,
            episode=episode,
            trigger_reason=policy.reason,
            error_code="INPUT_TOKEN_LIMIT",
            error_message=None,
            notice="诊断上下文超过配置的输入 Token 上限，当前返回确定性诊断。",
            deterministic_result=deterministic.model_dump(mode="json"),
            started=started,
            workflow_run_id=workflow_run_id,
            call_stage=call_stage,
            student_actor=student_actor,
        )

    # The governor checks quota only for new physical attempts, after replay lookup.
    last_error: Exception | None = None
    completion = None
    explanation = None
    attempts = 0
    route = settings.ai_provider or "provider"
    attempted_routes: list[str] = []
    governor = GovernedAIInvocation(
        db,
        diagnosis,
        settings,
        call_stage=call_stage,
        episode=episode,
        knowledge_case_ids=tuple(k.case_id for k in knowledge if k.case_id),
        source_snapshot=memory_sources,
        execution_context={"context_policy": CONTEXT_POLICY_VERSION,
                           "context_contract": CONTEXT_CONTRACT_VERSION},
        operation_key=(
            f"workflow:{workflow_run_id}:{call_stage}" if workflow_run_id
            else f"diagnosis:{diagnosis.id}:{operation_request_id or 'legacy'}:{call_stage}"
        ),
    )
    for candidate_route, candidate in clients:
        route = candidate_route
        ai = candidate
        attempted_routes.append(candidate_route)
        for _ in range(settings.ai_max_retries + 1):
            try:
                completion = governor.complete_json(
                    ai,
                    system_prompt=system_prompt,
                    user_prompt=user_prompt,
                )
                explanation = _validate_explanation(completion.content, payload)
                break
            except AIQuotaDenied as exc:
                last_error = exc
                break
            except (AIProviderError, ValidationError, ValueError, json.JSONDecodeError) as exc:
                last_error = exc
                # Retry only known failures; uncertain physical requests are not repeated.
                if not governor.retry(exc):
                    break
        if explanation is not None or (last_error is not None and not governor.retry(last_error)):
            break
    attempts = governor.attempts
    if isinstance(last_error, AIQuotaDenied):
        payload._context_manifest["reason_codes"].append(
            "source_changed" if "KNOWLEDGE" in last_error.code else
            "scope_unavailable" if ("SCOPE" in last_error.code
                                    or last_error.code == "AI_RESULT_STALE")
            else "governance_denied")
    if not attempts and isinstance(last_error, AIQuotaDenied):
        return _skipped_response(
            db,
            diagnosis=diagnosis,
            settings=settings,
            payload=payload,
            prompt_hash=prompt_hash,
            knowledge=knowledge,
            memory_sources=memory_sources,
            episode=episode,
            trigger_reason=policy.reason,
            error_code=last_error.code,
            error_message=None,
            notice="AI 调用配额检查未通过，当前返回确定性诊断。",
            deterministic_result=deterministic.model_dump(mode="json"),
            started=started,
            workflow_run_id=workflow_run_id,
            call_stage=call_stage,
            student_actor=student_actor,
        )
    duration_ms = int((time.monotonic() - started) * 1000)
    local_fallback = len(clients) > 1 and route == "cloud"
    if explanation is None:
        route_path = (
            "cache_miss → "
            + " → ".join(f"{item}_failed" for item in attempted_routes)
            + " → deterministic_fallback"
        )
        saved, created = _save_record(
            db,
            diagnosis=diagnosis,
            settings=settings,
            payload=payload,
            prompt_hash=prompt_hash,
            status="failed",
            attempt_count=attempts,
            duration_ms=duration_ms,
            explanation=None,
            knowledge=knowledge,
            memory_sources=memory_sources,
            error_code="AI_OUTPUT_OR_PROVIDER_FAILED",
            error_message=_safe_error_summary(last_error),
            episode=episode,
            trigger_reason=policy.reason,
            cache_status="miss",
            route=route,
            route_path=route_path,
            validation_status="failed",
            fallback_reason=(
                "LOCAL_AND_CLOUD_FAILED" if len(attempted_routes) > 1 else "DETERMINISTIC_TEMPLATE"
            ),
            estimated_cost=governor.estimated_cost,
            provider=ai.provider,
            model_name=ai.model,
            transport=client_transport,
            workflow_run_id=workflow_run_id,
            call_stage=call_stage,
        )
        if not created:
            return serialize_ai_call(saved, settings)
        _authorize_projection(db, diagnosis, student_actor)
        diagnosis.ai_enhancement = {
            "status": "failed_fallback",
            "trigger_reason": policy.reason,
            "route": route,
            "route_path": route_path,
            "cache_status": "miss",
            "fallback_reason": (
                "LOCAL_AND_CLOUD_FAILED" if len(attempted_routes) > 1 else "DETERMINISTIC_TEMPLATE"
            ),
            "call_record_id": saved.id,
        }
        db.commit()
        return _response(
            saved,
            None,
            knowledge,
            settings,
            "AI 输出未通过校验或 Provider 调用失败，已降级为规则诊断。",
            enhancement_status="failed_fallback",
            trigger_reason=policy.reason,
            route=route,
            route_path=route_path,
            deterministic_result=deterministic.model_dump(mode="json"),
        )

    route_path_parts = ["cache_miss"]
    route_path_parts.extend(f"{item}_failed" for item in attempted_routes[:-1])
    route_path_parts.append(f"{route}_success")
    route_path = " → ".join(route_path_parts)
    saved, created = _save_record(
        db,
        diagnosis=diagnosis,
        settings=settings,
        payload=payload,
        prompt_hash=prompt_hash,
        status="succeeded",
        attempt_count=attempts,
        duration_ms=duration_ms,
        explanation=explanation,
        knowledge=knowledge,
        memory_sources=memory_sources,
        input_tokens=completion.input_tokens if completion else None,
        output_tokens=completion.output_tokens if completion else None,
        episode=episode,
        trigger_reason=policy.reason,
        cache_status="miss",
        route=route,
        route_path=route_path,
        validation_status="passed",
        fallback_reason="LOCAL_FAILED_CLOUD_USED" if local_fallback else None,
        estimated_cost=governor.estimated_cost,
        provider=ai.provider,
        model_name=ai.model,
        transport=client_transport,
        workflow_run_id=workflow_run_id,
        call_stage=call_stage,
    )
    if not created:
        return serialize_ai_call(saved, settings)
    _authorize_projection(db, diagnosis, student_actor)
    from app.services.memory import record_uses

    record_uses(db, diagnosis, knowledge, target_type="cache", target_id=cache_fingerprint,
                use_kind="derived", sources=selected_sources(
                    memory_sources, {item.case_id or item.chunk_id for item in knowledge}))
    db.add(
        AIExplanationCache(
            fingerprint=cache_fingerprint,
            explanation_json=explanation.model_dump(mode="json"),
            provider=ai.provider,
            model_name=ai.model,
            prompt_version=settings.ai_prompt_version,
            schema_version=settings.ai_schema_version,
            ruleset_version=diagnosis.ruleset_version,
            fault_tree_version=fault_tree_version,
            knowledge_version="|".join(sorted(item.chunk_id for item in knowledge)) or None,
            created_at=now,
            expires_at=now + timedelta(seconds=settings.ai_cache_ttl_seconds),
        )
    )
    enhancement_status = "local_success" if route == "local" else "cloud_success"
    diagnosis.ai_enhancement = {
        "status": enhancement_status,
        "trigger_reason": policy.reason,
        "route": route,
        "route_path": route_path,
        "cache_status": "miss",
        "call_record_id": saved.id,
    }
    db.commit()
    return _response(
        saved,
        explanation,
        knowledge,
        settings,
        "此接口仅补充解释；错误类型、规则证据和故障树结果仍以确定性诊断为准。",
        enhancement_status=enhancement_status,
        trigger_reason=policy.reason,
        route=route,
        route_path=route_path,
        deterministic_result=deterministic.model_dump(mode="json"),
    )
