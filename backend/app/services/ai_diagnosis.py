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
from app.ai.context_sanitizer import audit_snapshot, build_safe_ai_input
from app.ai.output_contract import OUTPUT_CONTRACT_VERSION, explanation_contract
from app.ai.prompts import build_prompts
from app.ai.schemas import (
    AIDiagnosisInput,
    AIExplanationResponse,
    AIKnowledgeReference,
    AIStatusResponse,
    AIStructuredExplanation,
)
from app.core.config import Settings
from app.knowledge.matcher import match_knowledge_case_definitions, match_knowledge_cases
from app.models.ai_call_record import AICallRecord
from app.models.ai_explanation_cache import AIExplanationCache
from app.models.device import Device
from app.models.diagnosis_episode import DiagnosisEpisode
from app.models.diagnosis_result import DiagnosisResult
from app.models.guidance_history import GuidanceHistory
from app.services.diagnosis_episode import upsert_episode
from app.services.experiment_packages import load_experiment_package_runtime
from app.services.lightweight_diagnosis import (
    budget_allowed,
    build_diagnosis_core,
    decide_ai_policy,
    estimate_ai_cost,
    explanation_fingerprint,
    render_deterministic_explanation,
)


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
    return [
        AIKnowledgeReference(
            chunk_id=item.case_id,
            source_key=item.source_ref,
            source_title=f"{item.experiment_type}: {item.symptom}",
            source_type="structured_case",
            source_uri=None,
            source_version=item.version,
            locator={"case_id": item.case_id},
            content=json.dumps(
                {
                    "caseId": item.case_id,
                    "experimentType": item.experiment_type,
                    "errorType": item.error_type,
                    "symptom": item.symptom,
                    "normalState": item.normal_state,
                    "evidence": item.evidence,
                    "possibleCauses": item.possible_causes,
                    "solutionSteps": item.solution_steps,
                    "teacherNotes": item.teacher_notes,
                    "rootCause": {
                        "value": item.root_cause_value,
                        "status": item.root_cause_status,
                    },
                },
                ensure_ascii=False,
                separators=(",", ":"),
            ),
            similarity=item.match_score,
            retrieval_scores={"structured_match": item.match_score},
            is_test_data=item.is_test_data,
        )
        for item in cases
    ]


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
    allowed_causes = set(allowed_cause_support)
    if not allowed_causes:
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
        attempt_count=attempt_count,
        duration_ms=duration_ms,
        input_snapshot={
            **_audit_snapshot(payload),
            "output_contract": explanation_contract(payload),
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
        is_test_data=diagnosis.is_test_data or any(item.is_test_data for item in knowledge),
    )
    db.add(record)
    try:
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
    return AIExplanationResponse(
        call_record_id=record.id,
        diagnosis_result_id=record.diagnosis_result_id,
        status=record.status,
        mode="ai_enhanced" if record.status == "succeeded" else "rules_only",
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
    explanation = None
    contract = (record.input_snapshot or {}).get("output_contract") or {}
    if record.output_json:
        try:
            explanation = AIStructuredExplanation.model_validate(record.output_json)
            if contract.get("version") != OUTPUT_CONTRACT_VERSION or any(
                step not in contract.get("allowed_steps", []) for step in explanation.steps
            ):
                raise ValueError("historical output lacks the current contract")
            explanation = explanation.model_copy(
                update={
                    "summary": contract["summary"],
                    "limitations": contract["limitations"],
                }
            )
        except (ValueError, KeyError, TypeError):
            # Preserve the historical audit row but never silently serve it as
            # a newly validated suggestion. Do not charge/call the provider again.
            return _response(
                record,
                None,
                [],
                settings,
                "历史解释未通过当前输出约束，请查看确定性诊断结果。",
                enhancement_status="failed_fallback",
            ).model_copy(
                update={
                    "status": "failed",
                    "mode": "rules_only",
                }
            )
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
        return serialize_ai_call(saved, settings)
    enhancement_status = "disabled" if error_code == "AI_NOT_CONFIGURED" else "skipped"
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


def explain_diagnosis(
    db: Session,
    device: Device,
    diagnosis: DiagnosisResult,
    settings: Settings,
    *,
    ai_client: AIClient | None = None,
    ai_clients: list[tuple[str, AIClient]] | None = None,
    user_question: str | None = None,
    workflow_state: dict[str, Any] | None = None,
    retrieved_knowledge: list[AIKnowledgeReference] | None = None,
    workflow_run_id: str | None = None,
    call_stage: str = "explanation",
) -> AIExplanationResponse:
    started = time.monotonic()
    existing = _workflow_ai_record(db, workflow_run_id, call_stage)
    if existing is not None:
        return serialize_ai_call(existing, settings)
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
    core = build_diagnosis_core(diagnosis, guidance, [item.chunk_id for item in knowledge])
    deterministic = render_deterministic_explanation(core)
    diagnosis.deterministic_core = core.model_dump(mode="json")
    diagnosis.deterministic_explanation = deterministic.model_dump(mode="json")
    episode = upsert_episode(db, device, diagnosis, guidance, settings)
    policy = decide_ai_policy(core, settings, episode=episode, user_question=user_question)
    payload = _build_input(
        diagnosis,
        guidance,
        knowledge,
        settings,
        episode_id=episode.id if episode else None,
        user_question=user_question,
        workflow_state=workflow_state,
    )
    # Persist and return only the allowlisted/redacted representation produced by
    # the privacy boundary, never the original retrieved chunk objects.
    knowledge = list(payload.knowledge)
    _, _, prompt_hash = build_prompts(payload, settings.ai_prompt_version)
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

    # Include the actual allowlisted input, not only a configured prompt label.
    cache_fingerprint = hashlib.sha256(f"{cache_fingerprint}:{prompt_hash}".encode()).hexdigest()
    skip_code: str | None = None
    notice: str | None = None
    if retrieval_error:
        skip_code = "KNOWLEDGE_MATCH_FAILED"
        notice = "结构化知识匹配失败，已降级为确定性诊断；未调用 AI。"
    elif not policy.should_call:
        skip_code = policy.reason
        notice = "确定性结果已足够，本次无需调用 AI。"
    estimated_input_tokens = (
        len(json.dumps(payload.model_dump(mode="json"), ensure_ascii=False)) // 4
    )
    if skip_code:
        return _skipped_response(
            db,
            diagnosis=diagnosis,
            settings=settings,
            payload=payload,
            prompt_hash=prompt_hash,
            knowledge=knowledge,
            episode=episode,
            trigger_reason=policy.reason,
            error_code=skip_code,
            error_message=retrieval_error,
            notice=notice or "AI 调用已跳过。",
            deterministic_result=deterministic.model_dump(mode="json"),
            started=started,
            workflow_run_id=workflow_run_id,
            call_stage=call_stage,
        )

    now = datetime.now(timezone.utc)
    cached = db.scalar(
        select(AIExplanationCache).where(
            AIExplanationCache.fingerprint == cache_fingerprint,
            AIExplanationCache.expires_at > now,
        )
    )
    if cached is not None:
        try:
            explanation = _validate_explanation(json.dumps(cached.explanation_json), payload)
        except (ValueError, TypeError):
            db.delete(cached)  # Rebuildable cache, not an immutable audit record.
            db.flush()
            cached = None
    if cached is not None:
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

    if not ai.configured:
        return _skipped_response(
            db,
            diagnosis=diagnosis,
            settings=settings,
            payload=payload,
            prompt_hash=prompt_hash,
            knowledge=knowledge,
            episode=episode,
            trigger_reason=policy.reason,
            error_code="AI_NOT_CONFIGURED",
            error_message=None,
            notice="AI Provider 未配置，当前仅返回确定性规则和故障树结果。",
            deterministic_result=deterministic.model_dump(mode="json"),
            started=started,
            workflow_run_id=workflow_run_id,
            call_stage=call_stage,
        )

    if settings.ai_require_knowledge and not knowledge:
        return _skipped_response(
            db,
            diagnosis=diagnosis,
            settings=settings,
            payload=payload,
            prompt_hash=prompt_hash,
            knowledge=knowledge,
            episode=episode,
            trigger_reason=policy.reason,
            error_code="KNOWLEDGE_NOT_READY",
            error_message=None,
            notice="尚无可用的已审核结构化知识案例，已保持确定性诊断模式。",
            deterministic_result=deterministic.model_dump(mode="json"),
            started=started,
            workflow_run_id=workflow_run_id,
            call_stage=call_stage,
        )

    if estimated_input_tokens > settings.ai_input_token_limit:
        return _skipped_response(
            db,
            diagnosis=diagnosis,
            settings=settings,
            payload=payload,
            prompt_hash=prompt_hash,
            knowledge=knowledge,
            episode=episode,
            trigger_reason=policy.reason,
            error_code="INPUT_TOKEN_LIMIT",
            error_message=None,
            notice="诊断上下文超过配置的输入 Token 上限，当前返回确定性诊断。",
            deterministic_result=deterministic.model_dump(mode="json"),
            started=started,
            workflow_run_id=workflow_run_id,
            call_stage=call_stage,
        )

    projected_cost = estimate_ai_cost(
        estimated_input_tokens, settings.ai_output_token_limit, settings
    )
    allowed, budget_reason = budget_allowed(
        db, device.id, settings, episode, projected_call_cost=projected_cost
    )
    if not allowed:
        return _skipped_response(
            db,
            diagnosis=diagnosis,
            settings=settings,
            payload=payload,
            prompt_hash=prompt_hash,
            knowledge=knowledge,
            episode=episode,
            trigger_reason=policy.reason,
            error_code=budget_reason or "AI_BUDGET_LIMIT",
            error_message=None,
            notice="AI 调用预算或频率限制已生效，当前返回确定性诊断。",
            deterministic_result=deterministic.model_dump(mode="json"),
            started=started,
            estimated_cost=projected_cost or 0.0,
            workflow_run_id=workflow_run_id,
            call_stage=call_stage,
        )

    system_prompt, user_prompt, prompt_hash = build_prompts(payload, settings.ai_prompt_version)
    last_error: Exception | None = None
    completion = None
    explanation = None
    attempts = 0
    route = settings.ai_provider or "provider"
    attempted_routes: list[str] = []
    for candidate_route, candidate in clients:
        route = candidate_route
        ai = candidate
        attempted_routes.append(candidate_route)
        for _ in range(settings.ai_max_retries + 1):
            attempts += 1
            try:
                completion = ai.complete_json(system_prompt=system_prompt, user_prompt=user_prompt)
                explanation = _validate_explanation(completion.content, payload)
                break
            except (AIProviderError, ValidationError, ValueError, json.JSONDecodeError) as exc:
                last_error = exc
                user_prompt = f"{user_prompt}\n上一次输出未通过结构或证据校验，请仅返回合法 JSON。"
        if explanation is not None:
            break
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
            error_code="AI_OUTPUT_OR_PROVIDER_FAILED",
            error_message=_safe_error_summary(last_error),
            episode=episode,
            trigger_reason=policy.reason,
            cache_status="miss",
            route=route,
            route_path=route_path,
            validation_status="failed",
            fallback_reason=(
                "LOCAL_AND_CLOUD_FAILED" if len(clients) > 1 else "DETERMINISTIC_TEMPLATE"
            ),
            estimated_cost=projected_cost,
            provider=ai.provider,
            model_name=ai.model,
            transport=client_transport,
            workflow_run_id=workflow_run_id,
            call_stage=call_stage,
        )
        if not created:
            return serialize_ai_call(saved, settings)
        diagnosis.ai_enhancement = {
            "status": "failed_fallback",
            "trigger_reason": policy.reason,
            "route": route,
            "route_path": route_path,
            "cache_status": "miss",
            "fallback_reason": (
                "LOCAL_AND_CLOUD_FAILED" if len(clients) > 1 else "DETERMINISTIC_TEMPLATE"
            ),
            "call_record_id": saved.id,
        }
        if episode:
            episode.ai_call_count += 1
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
        input_tokens=completion.input_tokens if completion else None,
        output_tokens=completion.output_tokens if completion else None,
        episode=episode,
        trigger_reason=policy.reason,
        cache_status="miss",
        route=route,
        route_path=route_path,
        validation_status="passed",
        fallback_reason="LOCAL_FAILED_CLOUD_USED" if local_fallback else None,
        estimated_cost=estimate_ai_cost(
            (
                completion.input_tokens
                if completion and completion.input_tokens
                else estimated_input_tokens
            ),
            completion.output_tokens if completion and completion.output_tokens else 0,
            settings,
        ),
        provider=ai.provider,
        model_name=ai.model,
        transport=client_transport,
        workflow_run_id=workflow_run_id,
        call_stage=call_stage,
    )
    if not created:
        return serialize_ai_call(saved, settings)
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
    if episode:
        episode.ai_call_count += 1
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
