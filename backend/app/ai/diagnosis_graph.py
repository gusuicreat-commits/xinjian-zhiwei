from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from functools import wraps
from time import perf_counter
from typing import Any, Literal

from langgraph.graph import END, START, StateGraph
from langgraph.runtime import Runtime
from langgraph.types import interrupt
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.clients import AIClient
from app.ai.context_sanitizer import sanitize_text
from app.ai.reasoning import build_evidence_registry, reason_about_causes
from app.ai.schemas import AIExplanationResponse, AIKnowledgeReference
from app.core.config import Settings
from app.diagnosis.schemas import DiagnosisOutcome, ExperimentTemplateContext
from app.diagnosis.workflow_schemas import DiagnosisState
from app.knowledge.validation import (
    build_reasoning_knowledge_constraints,
    validate_reasoning_against_knowledge,
)
from app.models.base import utc_now
from app.models.classroom import ExperimentSession
from app.models.device import Device
from app.models.diagnosis_result import DiagnosisResult
from app.models.diagnosis_workflow import DiagnosisWorkflowReview, DiagnosisWorkflowRun
from app.models.guidance_history import GuidanceHistory
from app.models.knowledge import KnowledgeCase
from app.services.ai_diagnosis import _match_structured_knowledge, explain_diagnosis
from app.services.diagnosis import (
    build_diagnosis_context,
    diagnose,
    save_diagnosis_result,
)
from app.services.guidance import generate_guidance
from app.services.lightweight_diagnosis import (
    build_diagnosis_core,
    render_deterministic_explanation,
)


@dataclass
class DiagnosisGraphContext:
    db: Session
    device: Device
    settings: Settings
    ai_client: AIClient | None = None
    ai_clients: list[tuple[str, AIClient]] | None = None
    review_payload: dict[str, Any] | None = None


class DiagnosisNodeExecutionError(RuntimeError):
    """A redacted node failure carrying only bounded observability metadata."""

    def __init__(self, node: str, duration_ms: float, error_type: str) -> None:
        super().__init__(f"diagnosis graph node {node} failed")
        self.node = node
        self.duration_ms = duration_ms
        self.error_type = error_type


def observed_node(name: str):
    """Record bounded, serializable per-node timing without leaking node inputs."""

    def decorate(function):
        @wraps(function)
        def wrapped(state, runtime):
            started = perf_counter()
            try:
                _workflow(runtime, state)
                update = function(state, runtime)
            except Exception as exc:
                duration_ms = round((perf_counter() - started) * 1000, 3)
                raise DiagnosisNodeExecutionError(name, duration_ms, type(exc).__name__) from exc
            duration_ms = round((perf_counter() - started) * 1000, 3)
            metrics = list(update.get("node_metrics") or [])
            metrics.append({"node": name, "duration_ms": duration_ms, "status": "succeeded"})
            update["node_metrics"] = metrics
            return update

        return wrapped

    return decorate


def _workflow(
    runtime: Runtime[DiagnosisGraphContext],
    state: DiagnosisState,
    *,
    for_update: bool = False,
) -> DiagnosisWorkflowRun:
    if for_update:
        record = runtime.context.db.scalar(
            select(DiagnosisWorkflowRun)
            .where(DiagnosisWorkflowRun.id == state["diagnosis_id"])
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    else:
        record = runtime.context.db.get(DiagnosisWorkflowRun, state["diagnosis_id"])
    if record is None:
        raise RuntimeError("diagnosis workflow business record no longer exists")
    expected_thread_id = f"diagnosis:{record.id}"
    experiment_session = runtime.context.db.get(ExperimentSession, record.experiment_session_id)
    if (
        record.graph_thread_id != expected_thread_id
        or state.get("diagnosis_id") != record.id
        or state.get("student_user_id") != record.student_user_id
        or state.get("experiment_session_id") != record.experiment_session_id
        or record.device_id != runtime.context.device.id
        or experiment_session is None
        or experiment_session.student_user_id != record.student_user_id
        or experiment_session.device_id != record.device_id
    ):
        raise RuntimeError("diagnosis checkpoint ownership validation failed")
    return record


def _diagnosis(runtime: Runtime[DiagnosisGraphContext], state: DiagnosisState) -> DiagnosisResult:
    diagnosis_id = state.get("diagnosis_result_id") or _workflow(runtime, state).diagnosis_result_id
    record = runtime.context.db.get(DiagnosisResult, diagnosis_id) if diagnosis_id else None
    if record is None:
        raise RuntimeError("workflow diagnosis result no longer exists")
    return record


def _guidance(
    runtime: Runtime[DiagnosisGraphContext], state: DiagnosisState
) -> list[GuidanceHistory]:
    diagnosis = _diagnosis(runtime, state)
    return list(
        runtime.context.db.scalars(
            select(GuidanceHistory)
            .where(GuidanceHistory.diagnosis_result_id == diagnosis.id)
            .order_by(GuidanceHistory.fault_tree_id)
        )
    )


@observed_node("context_builder")
def context_builder(
    state: DiagnosisState, runtime: Runtime[DiagnosisGraphContext]
) -> dict[str, Any]:
    context = build_diagnosis_context(
        runtime.context.db,
        runtime.context.device,
        evaluated_at=datetime.fromisoformat(state["evaluated_at"]),
        lookback_seconds=state["lookback_seconds"],
        experiment_template=(
            ExperimentTemplateContext.model_validate(state["experiment_template"])
            if state.get("experiment_template")
            else None
        ),
        experiment_id=state.get("experiment_id"),
        experiment_version=state.get("experiment_version"),
    )
    last_seen_at = context.last_seen_at
    if last_seen_at is None:
        device_status = "never_seen"
    else:
        evaluated_at = context.evaluated_at
        last_seen = (
            last_seen_at
            if last_seen_at.tzinfo
            else last_seen_at.replace(tzinfo=evaluated_at.tzinfo)
        )
        elapsed = (evaluated_at - last_seen).total_seconds()
        device_status = (
            "online"
            if elapsed <= runtime.context.settings.device_offline_after_seconds
            else "offline"
        )
    # Checkpoints retain bounded, sanitized observations rather than raw payloads.
    sensor_values = [
        {
            "id": item.id,
            "sensor_type": item.sensor_type,
            "metric_key": item.metric_key,
            "value": item.value,
            "unit": item.unit,
            "observed_at": item.observed_at.isoformat(),
        }
        for item in context.readings[-200:]
    ]
    experiment_type = (
        context.experiment_id
        or (
            context.experiment_template.template_id
            if context.experiment_template
            else None
        )
        or (context.readings[-1].sensor_type if context.readings else None)
    )
    return {
        "device_status": {
            "device_id": context.device_id,
            "status": device_status,
            "last_seen_at": last_seen_at.isoformat() if last_seen_at else None,
            "firmware_version": context.device.firmware_version if context.device else None,
        },
        "logs": [
            {
                "id": item.id,
                "level": item.level,
                "event_code": item.event_code,
                "occurred_at": item.occurred_at.isoformat(),
            }
            for item in context.logs[-100:]
        ],
        "experiment_type": experiment_type,
        "sensor_data": sensor_values,
        "sensor_values": sensor_values,
        "experiment_context": {
            "experiment_id": context.experiment_id,
            "experiment_version": context.experiment_version,
            "definition_hash": context.experiment_definition_hash,
            "template": (
                context.experiment_template.model_dump(mode="json")
                if context.experiment_template
                else None
            ),
        },
        "context_ref": {
            "evaluated_at": context.evaluated_at.isoformat(),
            "last_seen_at": context.last_seen_at.isoformat() if context.last_seen_at else None,
            "log_refs": [item.id for item in context.logs],
            "heartbeat_refs": [item.id for item in context.heartbeats],
            "reading_refs": [item.id for item in context.readings],
            "telemetry_summary": {
                "log_count": len(context.logs),
                "heartbeat_count": len(context.heartbeats),
                "reading_count": len(context.readings),
                "error_codes": sorted(
                    {item.event_code for item in context.logs if item.event_code}
                ),
                "metric_keys": sorted({item.metric_key for item in context.readings}),
            },
        },
        "status": "deterministic_analysis",
        "diagnosis_status": "deterministic_analysis",
        "historical_failures": 0,
        "node_trace": ["context_builder"],
    }


@observed_node("rule_engine")
def rule_engine(state: DiagnosisState, runtime: Runtime[DiagnosisGraphContext]) -> dict[str, Any]:
    db = runtime.context.db
    workflow = _workflow(runtime, state)
    record = (
        db.get(DiagnosisResult, workflow.diagnosis_result_id)
        if workflow.diagnosis_result_id
        else None
    )
    if record is None:
        context = build_diagnosis_context(
            db,
            runtime.context.device,
            evaluated_at=datetime.fromisoformat(state["evaluated_at"]),
            lookback_seconds=state["lookback_seconds"],
            experiment_template=(
                ExperimentTemplateContext.model_validate(state["experiment_template"])
                if state.get("experiment_template")
                else None
            ),
            experiment_id=state.get("experiment_id"),
            experiment_version=state.get("experiment_version"),
        )
        outcome = diagnose(context)
        record = save_diagnosis_result(
            db,
            runtime.context.device,
            context,
            outcome,
            commit=False,
        )
        workflow.diagnosis_result_id = record.id
        workflow.is_test_data = record.is_test_data
        # The result and its workflow reference are one transaction. A saver
        # failure can therefore replay this node without creating an orphan or a
        # second deterministic diagnosis result.
        db.commit()
        db.refresh(record)
    else:
        outcome = DiagnosisOutcome.model_validate(
            {
                "ruleset_version": record.ruleset_version,
                "ruleset_hash": record.ruleset_hash,
                "input_fingerprint": record.input_fingerprint,
                "matches": record.matched_rules,
            }
        )
    rule_hits = [
        {
            "rule_id": item.rule_id,
            "error_type": item.error_type,
            "summary": item.summary,
            "priority": item.priority,
            "evidence": [
                {
                    "fact": evidence.fact,
                    "observed_value": evidence.observed_value,
                    "evidence_refs": [
                        f"{kind}:{detail[key]}"
                        for detail in evidence.details
                        for key, kind in (("log_id", "log"), ("reading_id", "reading"))
                        if detail.get(key)
                    ],
                }
                for evidence in item.evidence
            ],
        }
        for item in outcome.matches
    ]
    return {
        "diagnosis_result_id": record.id,
        "error_type": rule_hits[0]["error_type"] if rule_hits else None,
        "evidence": [
            {"rule_id": hit["rule_id"], **item}
            for hit in rule_hits
            for item in hit["evidence"]
        ],
        "rule_hits": rule_hits,
        "rule_engine_version": outcome.ruleset_version,
        "rule_engine_hash": outcome.ruleset_hash,
        "input_fingerprint": outcome.input_fingerprint,
        "node_trace": ["rule_engine"],
    }


@observed_node("fault_tree_analyzer")
def fault_tree_analyzer(
    state: DiagnosisState, runtime: Runtime[DiagnosisGraphContext]
) -> dict[str, Any]:
    diagnosis = _diagnosis(runtime, state)
    guidance = generate_guidance(runtime.context.db, runtime.context.device, diagnosis)
    core = build_diagnosis_core(diagnosis, guidance)
    deterministic = render_deterministic_explanation(core)
    diagnosis.deterministic_core = core.model_dump(mode="json")
    diagnosis.deterministic_explanation = deterministic.model_dump(mode="json")
    runtime.context.db.commit()
    candidates: list[dict[str, Any]] = []
    for item in guidance:
        for cause in item.ranked_causes:
            candidates.append(
                {
                    "cause_id": str(cause.get("cause_id", "")),
                    "name": str(cause.get("title", "")),
                    "score": float(cause.get("score", 0.0)) / 100.0,
                    "evidence_refs": [
                        f"{kind}:{detail[key]}"
                        for evidence in cause.get("evidence", [])
                        for detail in evidence.get("details", [])
                        for key, kind in (("log_id", "log"), ("reading_id", "reading"))
                        if detail.get(key)
                    ]
                    or [f"rule:{item.fault_tree_id}:{cause.get('cause_id', '')}"],
                }
            )
    candidates.sort(key=lambda item: (-item["score"], item["cause_id"]))
    allowed_actions = [
        {
            "action_id": (
                f"hint:{item.fault_tree_id}:{hint.get('cause_id', 'general')}:"
                f"{hint.get('level', item.hint_level)}"
            ),
            "cause_id": str(hint.get("cause_id") or ""),
            "text": sanitize_text(hint.get("text"), max_chars=1000),
            "source": "fault_tree",
        }
        for item in guidance
        for hint in item.hints
        if hint.get("text")
    ]
    failure_count = max((item.failure_count for item in guidance), default=0)
    anomaly_duration = max((item.anomaly_duration_seconds for item in guidance), default=0)
    return {
        "possible_causes": candidates,
        "fault_tree_candidates": candidates,
        "fault_tree_version": guidance[0].fault_tree_version if guidance else "none",
        "evidence_score": core.confidence,
        "hint_level": core.hint_level,
        "guidance_level": core.hint_level,
        "historical_failures": failure_count,
        "failure_count": failure_count,
        "anomaly_duration_seconds": anomaly_duration,
        "deterministic_result": deterministic.model_dump(mode="json"),
        "allowed_verification_actions": allowed_actions,
        "node_trace": ["fault_tree_analyzer"],
    }


@observed_node("ai_reasoning")
def ai_reasoning_node(
    state: DiagnosisState, runtime: Runtime[DiagnosisGraphContext]
) -> dict[str, Any]:
    diagnosis = _diagnosis(runtime, state)
    graph_knowledge, _ = _load_graph_knowledge(state, runtime)
    reasoning_state = dict(state)
    reasoning_state["knowledge_constraints"] = build_reasoning_knowledge_constraints(
        state.get("experiment_context"), graph_knowledge
    )
    result, mode = reason_about_causes(
        runtime.context.db,
        diagnosis,
        reasoning_state,
        runtime.context.settings,
        workflow_run_id=state["diagnosis_id"],
        call_stage=(
            f"reasoning:feedback:{state['student_feedback']['id']}"
            if (state.get("student_feedback") or {}).get("id")
            else "reasoning"
        ),
        ai_client=runtime.context.ai_client,
        ai_clients=runtime.context.ai_clients,
    )
    reasoned_causes = [item.model_dump(mode="json") for item in result.ranked_causes]
    return {
        "reasoned_causes": reasoned_causes,
        "possible_causes": reasoned_causes,
        "reasoning_status": (
            result.conclusion
            if mode == "ai" or result.conclusion == "unknown"
            else "fallback"
        ),
        "reasoning_summary": result.summary,
        "reasoning_mode": mode,
        "missing_evidence": result.missing_evidence,
        "next_verification_action": result.next_verification_action,
        "evidence_conflict": result.conflict,
        "evidence_registry": build_evidence_registry(reasoning_state),
        "node_trace": ["ai_reasoning"],
    }


def _retrieval_query(state: DiagnosisState) -> str:
    parts = [state.get("question") or ""]
    parts.extend(str(item.get("error_type", "")) for item in state.get("rule_hits", []))
    parts.extend(str(item.get("name", "")) for item in state.get("fault_tree_candidates", []))
    return "；".join(dict.fromkeys(item for item in parts if item))


_LOCATOR_KEYS = {
    "page",
    "page_number",
    "section",
    "chapter",
    "heading",
    "chunk_index",
    "case_id",
}
_RETRIEVAL_SCORE_KEYS = {"structured_match"}


def _safe_locator(locator: Any) -> dict[str, Any]:
    if not isinstance(locator, dict):
        return {}
    return {
        key: (sanitize_text(value, max_chars=200) if isinstance(value, str) else value)
        for key, value in locator.items()
        if key in _LOCATOR_KEYS and isinstance(value, (str, int, float, bool))
    }


def _knowledge_state_reference(item: AIKnowledgeReference) -> dict[str, Any]:
    """Project a retrieved chunk into a bounded checkpoint/public reference.

    Full chunk text is reloaded by exact approved chunk ID only at the synthesis
    node. It never enters LangGraph checkpoint state or workflow API payloads.
    """

    return {
        "chunk_id": sanitize_text(item.chunk_id, max_chars=100),
        "case_id": sanitize_text(item.case_id or item.chunk_id, max_chars=100),
        "source_id": sanitize_text(item.source_key, max_chars=200),
        "title": sanitize_text(item.source_title, max_chars=200),
        "score": float(item.similarity),
        "metadata": {
            "source_type": sanitize_text(item.source_type, max_chars=100)
            if item.source_type
            else None,
            "source_version": sanitize_text(item.source_version, max_chars=100)
            if item.source_version
            else None,
            "locator": _safe_locator(item.locator),
            "review_status": "approved",
            "retrieval_scores": {
                key: float(value)
                for key, value in item.retrieval_scores.items()
                if key in _RETRIEVAL_SCORE_KEYS and isinstance(value, (int, float))
            },
            "is_test_data": bool(item.is_test_data),
        },
    }


def _safe_graph_knowledge(
    references: list[AIKnowledgeReference], settings: Settings
) -> list[AIKnowledgeReference]:
    """Apply the checkpoint/provider text boundary without storing raw chunks."""

    return [
        item.model_copy(
            update={
                "source_title": sanitize_text(item.source_title, max_chars=200),
                "source_key": sanitize_text(item.source_key, max_chars=200),
                "source_uri": None,
                "source_version": sanitize_text(item.source_version, max_chars=100)
                if item.source_version
                else None,
                "locator": _safe_locator(item.locator),
                "content": sanitize_text(
                    item.content,
                    max_chars=settings.ai_knowledge_content_max_chars,
                ),
            }
        )
        for item in references
    ]


def _load_graph_knowledge(
    state: DiagnosisState,
    runtime: Runtime[DiagnosisGraphContext],
) -> tuple[list[AIKnowledgeReference], list[dict[str, Any]]]:
    requested = [
        item
        for item in state.get("retrieved_chunks", [])
        if isinstance(item, dict) and item.get("chunk_id")
    ]
    chunk_ids = [str(item["chunk_id"]) for item in requested]
    if not chunk_ids:
        return [], []
    rows = list(
        runtime.context.db.scalars(
            select(KnowledgeCase).where(
                KnowledgeCase.id.in_(chunk_ids),
                KnowledgeCase.review_status == "approved",
                KnowledgeCase.root_cause_status == "confirmed",
                KnowledgeCase.facts_locked.is_(True),
                KnowledgeCase.quality_check_passed.is_(True),
            )
        )
    )
    by_id = {item.id: item for item in rows}
    references: list[AIKnowledgeReference] = []
    safe_state_refs: list[dict[str, Any]] = []
    for state_item in requested:
        case = by_id.get(str(state_item["chunk_id"]))
        if case is None:
            continue
        metadata = state_item.get("metadata") or {}
        reference = AIKnowledgeReference(
            chunk_id=case.id,
            source_key=case.source_ref,
            source_title=f"{case.experiment_type}: {case.symptom}",
            source_type="structured_case",
            source_uri=None,
            source_version=case.version,
            locator={"case_id": case.id},
            content=json.dumps(
                {
                    "caseId": case.id,
                    "experimentType": case.experiment_type,
                    "errorType": case.error_type,
                    "symptom": case.symptom,
                    "normalState": case.normal_state,
                    "evidence": case.evidence,
                    "possibleCauses": case.possible_causes,
                    "solutionSteps": case.solution_steps,
                    "teacherNotes": case.teacher_notes,
                    "rootCause": {
                        "value": case.root_cause_value,
                        "status": case.root_cause_status,
                    },
                },
                ensure_ascii=False,
                separators=(",", ":"),
            ),
            similarity=float(state_item.get("score") or 0.0),
            review_status="approved",
            retrieval_scores={
                key: float(value)
                for key, value in (metadata.get("retrieval_scores") or {}).items()
                if key in _RETRIEVAL_SCORE_KEYS and isinstance(value, (int, float))
            },
            is_test_data=case.is_test_data,
        )
        references.append(reference)
        safe_state_refs.append(_knowledge_state_reference(reference))
    return _safe_graph_knowledge(references, runtime.context.settings), safe_state_refs


@observed_node("knowledge_context")
def knowledge_context(
    state: DiagnosisState, runtime: Runtime[DiagnosisGraphContext]
) -> dict[str, Any]:
    diagnosis = _diagnosis(runtime, state)
    guidance = _guidance(runtime, state)
    query = _retrieval_query(state)
    references = _match_structured_knowledge(
        runtime.context.db,
        diagnosis,
        guidance,
        runtime.context.settings,
    )
    knowledge_context = [_knowledge_state_reference(item) for item in references]
    supply = {
        "status": "available" if references else "no_approved_case",
        "case_ids": [item.chunk_id for item in references],
        "provides": [
            "experiment_definition",
            "normal_conditions",
            "standard_fault_mappings",
            "teacher_confirmed_cases",
        ],
        "note": (
            "已在 AI 推理前提供实验定义、正常条件、故障映射与教师确认案例。"
            if references
            else "没有已审核案例；AI 仍只能在规则和故障树约束内推理。"
        ),
    }
    return {
        "retrieval_query": query,
        "knowledge_context": knowledge_context,
        "knowledge_supply": supply,
        "retrieved_chunks": knowledge_context,
        "needs_rag": False,
        "status": "retrieving",
        "diagnosis_status": "retrieving",
        "node_trace": ["knowledge_context"],
    }


@observed_node("knowledge_validation")
def knowledge_validation(
    state: DiagnosisState, runtime: Runtime[DiagnosisGraphContext]
) -> dict[str, Any]:
    graph_knowledge, _ = _load_graph_knowledge(state, runtime)
    validation_state = dict(state)
    validation_state["knowledge_constraints"] = build_reasoning_knowledge_constraints(
        state.get("experiment_context"), graph_knowledge
    )
    result = validate_reasoning_against_knowledge(validation_state)
    rejected = result["status"] == "rejected"
    return {
        "knowledge_validation": result,
        "evidence_conflict": bool(state.get("evidence_conflict")) or rejected,
        "need_teacher_help": bool(state.get("need_teacher_help")) or rejected,
        "needs_teacher": bool(state.get("needs_teacher")) or rejected,
        "status": "deterministic_analysis",
        "diagnosis_status": "deterministic_analysis",
        "node_trace": ["knowledge_validation"],
    }


def route_after_knowledge_validation(
    state: DiagnosisState,
) -> Literal["ai_explanation", "teacher_review"]:
    validation = state.get("knowledge_validation") or {}
    return "teacher_review" if validation.get("status") == "rejected" else "ai_explanation"


@observed_node("ai_explanation")
def ai_explanation(
    state: DiagnosisState, runtime: Runtime[DiagnosisGraphContext]
) -> dict[str, Any]:
    diagnosis = _diagnosis(runtime, state)
    graph_knowledge, safe_state_refs = _load_graph_knowledge(state, runtime)

    # LangGraph owns sequencing only. The governed AI service receives the
    # deterministic state and may explain it, never replace it.
    response: AIExplanationResponse = explain_diagnosis(
        runtime.context.db,
        runtime.context.device,
        diagnosis,
        runtime.context.settings,
        ai_client=runtime.context.ai_client,
        ai_clients=runtime.context.ai_clients,
        user_question=state.get("question"),
        workflow_state={
            key: state.get(key)
            for key in (
                "device_status",
                "experiment_type",
                "logs",
                "sensor_data",
                "sensor_values",
                "experiment_context",
                "error_type",
                "evidence",
                "possible_causes",
                "reasoned_causes",
                "reasoning_status",
                "reasoning_summary",
                "missing_evidence",
                "next_verification_action",
                "evidence_conflict",
                "evidence_registry",
                "allowed_verification_actions",
                "knowledge_supply",
                "knowledge_validation",
                "knowledge_context",
                "hint_level",
                "student_feedback",
                "historical_failures",
                "need_teacher_help",
                "diagnosis_status",
            )
        },
        retrieved_knowledge=graph_knowledge,
        workflow_run_id=state["diagnosis_id"],
        call_stage=(
            f"explanation:feedback:{state['student_feedback']['id']}"
            if (state.get("student_feedback") or {}).get("id")
            else "explanation"
        ),
    )
    return {
        "ai_result": (
            response.explanation.model_dump(mode="json") if response.explanation else None
        ),
        "retrieved_chunks": safe_state_refs,
        "model_id": runtime.context.settings.ai_model,
        "status": "ai_analysis",
        "diagnosis_status": "ai_analysis",
        "node_trace": ["ai_explanation"],
    }


def feedback_handler(
    state: DiagnosisState, runtime: Runtime[DiagnosisGraphContext]
) -> dict[str, Any]:
    _diagnosis(runtime, state)
    feedback = interrupt(
        {
            "kind": "student_feedback",
            "workflow_id": state["diagnosis_id"],
            "diagnosis_result_id": state.get("diagnosis_result_id"),
            "allowed_actions": ["resolved", "unresolved", "request_teacher_help"],
            "hint_level": state.get("hint_level", 1),
            "attempt_count": state.get("attempt_count", 0),
            "next_verification_action": state.get("next_verification_action"),
            "rule_hits": state.get("rule_hits", []),
            "candidates": state.get("fault_tree_candidates", []),
            "retrieved_chunks": state.get("retrieved_chunks", []),
            "ai_result": state.get("ai_result"),
            "deterministic_result": state.get("deterministic_result"),
            "instruction": "请反馈：resolved / unresolved / request_teacher_help",
        }
    )
    if not isinstance(feedback, dict) or feedback.get("action") not in {
        "resolved",
        "unresolved",
        "request_teacher_help",
    }:
        raise ValueError("invalid student feedback resume payload")
    return {
        "student_feedback": {
            "id": sanitize_text(feedback.get("id"), max_chars=100),
            "action": feedback["action"],
            "note": sanitize_text(feedback.get("note"), max_chars=1000)
            if feedback.get("note")
            else None,
            "created_at": sanitize_text(feedback.get("created_at"), max_chars=100),
        },
        "node_trace": ["feedback_handler"],
    }


@observed_node("escalation_handler")
def escalation_handler(
    state: DiagnosisState, runtime: Runtime[DiagnosisGraphContext]
) -> dict[str, Any]:
    guidance = _guidance(runtime, state)
    feedback_action = (state.get("student_feedback") or {}).get("action")
    attempt_count = int(state.get("attempt_count") or 0)
    if feedback_action == "unresolved":
        attempt_count += 1
    failure_count = max(
        int(state.get("failure_count") or 0),
        max((item.failure_count for item in guidance), default=0),
    )
    if feedback_action == "unresolved":
        failure_count += 1
    evaluated_at = datetime.fromisoformat(state["evaluated_at"])
    current_duration = max(
        0,
        int((datetime.now(evaluated_at.tzinfo) - evaluated_at).total_seconds()),
    )
    anomaly_duration = max(
        current_duration,
        int(state.get("anomaly_duration_seconds") or 0),
        max((item.anomaly_duration_seconds for item in guidance), default=0),
    )
    hint_level = max(
        state.get("hint_level", state.get("guidance_level", 1)),
        max((item.hint_level for item in guidance), default=1),
    )
    if feedback_action == "unresolved":
        hint_level = min(4, hint_level + 1)
    elif feedback_action == "request_teacher_help":
        hint_level = 4

    score = state.get("evidence_score", 0.0)
    ai_conflicts_with_rules = bool(
        state.get("ai_result")
        and state.get("rule_hits")
        and state["ai_result"].get("error_type")
        not in {item["error_type"] for item in state["rule_hits"]}
    )
    evidence_conflict = bool(state.get("evidence_conflict"))
    reasoning_unknown = state.get("reasoning_status") == "unknown"
    needs_teacher = feedback_action != "resolved" and (
        feedback_action == "request_teacher_help"
        or hint_level >= 4
        or attempt_count >= runtime.context.settings.diagnosis_teacher_max_attempts
        or anomaly_duration
        >= runtime.context.settings.diagnosis_teacher_duration_seconds
        or score < runtime.context.settings.diagnosis_teacher_review_score
        or ai_conflicts_with_rules
        or evidence_conflict
        or reasoning_unknown
    )
    diagnosis_status = (
        "waiting_teacher"
        if needs_teacher
        else "waiting_feedback"
        if feedback_action in {None, "unresolved"}
        else "completed"
    )
    return {
        "hint_level": hint_level,
        "guidance_level": hint_level,
        "failure_count": failure_count,
        "historical_failures": failure_count,
        "attempt_count": attempt_count,
        "anomaly_duration_seconds": anomaly_duration,
        "need_teacher_help": needs_teacher,
        "needs_teacher": needs_teacher,
        "status": diagnosis_status,
        "diagnosis_status": diagnosis_status,
        "node_trace": ["escalation_handler"],
    }


def route_after_escalation(
    state: DiagnosisState,
) -> Literal[
    "teacher_review",
    "persist_result",
    "knowledge_context",
    "feedback_handler",
]:
    if state.get("needs_teacher"):
        return "teacher_review"
    feedback_action = (state.get("student_feedback") or {}).get("action")
    if feedback_action == "unresolved":
        return "knowledge_context"
    if feedback_action is None:
        return "feedback_handler"
    return "persist_result"


def route_after_explanation(
    state: DiagnosisState,
) -> Literal["escalation_handler", "feedback_handler", "persist_result"]:
    if not state.get("error_type"):
        return "persist_result"
    if state.get("student_feedback"):
        return "feedback_handler"
    return "escalation_handler"


def teacher_review(state: DiagnosisState) -> dict[str, Any]:
    decision = interrupt(
        {
            "kind": "teacher_review",
            "workflow_id": state["diagnosis_id"],
            "diagnosis_result_id": state.get("diagnosis_result_id"),
            "guidance_level": state.get("guidance_level"),
            "evidence_score": state.get("evidence_score"),
            "candidates": state.get("fault_tree_candidates", []),
            "rule_hits": state.get("rule_hits", []),
            "retrieved_chunks": state.get("retrieved_chunks", []),
            "ai_result": state.get("ai_result"),
            "deterministic_result": state.get("deterministic_result"),
            "instruction": "请审核：approve / edit / reject",
        }
    )
    return {"teacher_review": decision, "node_trace": ["teacher_review"]}


def route_after_review(
    state: DiagnosisState,
) -> Literal["persist_result", "reject_result"]:
    review = state.get("teacher_review") or {}
    return "persist_result" if review.get("action") in {"approve", "edit"} else "reject_result"


def _approved_result(state: DiagnosisState) -> dict[str, Any]:
    base = dict(state.get("ai_result") or state.get("deterministic_result") or {})
    review = state.get("teacher_review") or {}
    edited = review.get("edited_result") or {}
    if review.get("action") == "edit":
        # Teachers may edit explanatory prose, never the deterministic rule facts,
        # evidence score, or Level computed by the backend.
        for key in ("summary", "possible_causes", "steps", "limitations"):
            if key in edited and edited[key] is not None:
                base[key] = edited[key]
    base["rules_preserved"] = True
    base["rule_hits"] = state.get("rule_hits", [])
    base["error_type"] = state.get("error_type") or base.get("error_type")
    base["evidence"] = state.get("evidence", [])
    base["evidence_score"] = state.get("evidence_score")
    base["hint_level"] = state.get("hint_level", state.get("guidance_level"))
    base["guidance_level"] = base["hint_level"]
    base["need_teacher_help"] = bool(state.get("need_teacher_help"))
    base["student_feedback"] = state.get("student_feedback")
    base["ai_reasoning"] = {
        "mode": state.get("reasoning_mode"),
        "status": state.get("reasoning_status"),
        "summary": state.get("reasoning_summary"),
        "ranked_causes": state.get("reasoned_causes", []),
        "missing_evidence": state.get("missing_evidence", []),
        "next_verification_action": state.get("next_verification_action"),
        "conflict": bool(state.get("evidence_conflict")),
    }
    base["knowledge_validation"] = state.get("knowledge_validation") or {}
    base["teacher_reviewed"] = bool(review)
    base["candidate_causes"] = state.get(
        "possible_causes", state.get("fault_tree_candidates", [])
    )
    base["knowledge_references"] = [
        {
            "chunk_id": item.get("chunk_id"),
            "case_id": item.get("case_id") or item.get("chunk_id"),
            "source_id": item.get("source_id"),
            "title": item.get("title"),
            "score": item.get("score"),
            "metadata": item.get("metadata") or {},
        }
        for item in state.get("retrieved_chunks", [])
    ]
    base["retrieval_query"] = state.get("retrieval_query")
    return base


def _persist_teacher_review(
    state: DiagnosisState,
    runtime: Runtime[DiagnosisGraphContext],
    workflow: DiagnosisWorkflowRun,
) -> None:
    """Atomically persist one accepted resume decision with its business result.

    A graph node can be replayed after a checkpoint write failure.  The one-review
    business invariant and database constraint make that replay idempotent.
    """

    decision = state.get("teacher_review") or {}
    if not decision:
        return
    audit_decision = runtime.context.review_payload or decision
    existing = runtime.context.db.scalar(
        select(DiagnosisWorkflowReview.id).where(
            DiagnosisWorkflowReview.workflow_run_id == workflow.id
        )
    )
    if existing is None:
        # The terminal node holds a FOR UPDATE lock on its workflow row, so this
        # check-and-insert sequence is serialized even for direct graph workers.
        # The unique constraint remains the final database invariant.
        runtime.context.db.add(
            DiagnosisWorkflowReview(
                workflow_run_id=workflow.id,
                reviewer_user_id=audit_decision["reviewer_user_id"],
                action=audit_decision["action"],
                comment=audit_decision.get("comment"),
                edited_result=audit_decision.get("edited_result"),
                created_at=utc_now(),
            )
        )
        workflow.resume_count = (workflow.resume_count or 0) + 1


@observed_node("persist_result")
def persist_result(
    state: DiagnosisState, runtime: Runtime[DiagnosisGraphContext]
) -> dict[str, Any]:
    # Lock again inside the terminal transaction. API-level locks are released by
    # earlier node commits and cannot protect direct worker/checkpoint replays.
    workflow = _workflow(runtime, state, for_update=True)
    result = _approved_result(state)
    _persist_teacher_review(state, runtime, workflow)
    workflow.final_result = result
    workflow.review_request = None
    workflow.status = "completed"
    workflow.current_node = "persist_result"
    workflow.completed_at = datetime.now().astimezone()
    runtime.context.db.commit()
    return {
        "status": "completed",
        "diagnosis_status": "completed",
        "node_trace": ["persist_result"],
    }


@observed_node("reject_result")
def reject_result(state: DiagnosisState, runtime: Runtime[DiagnosisGraphContext]) -> dict[str, Any]:
    workflow = _workflow(runtime, state, for_update=True)
    _persist_teacher_review(state, runtime, workflow)
    workflow.final_result = None
    workflow.review_request = None
    workflow.status = "rejected"
    workflow.current_node = "reject_result"
    workflow.completed_at = datetime.now().astimezone()
    runtime.context.db.commit()
    return {
        "status": "rejected",
        "diagnosis_status": "rejected",
        "node_trace": ["reject_result"],
    }


def build_diagnosis_graph(checkpointer: Any):
    builder = StateGraph(DiagnosisState, context_schema=DiagnosisGraphContext)
    builder.add_node("context_builder", context_builder)
    builder.add_node("rule_engine", rule_engine)
    builder.add_node("fault_tree_analyzer", fault_tree_analyzer)
    builder.add_node("knowledge_context", knowledge_context)
    builder.add_node("ai_reasoning", ai_reasoning_node)
    builder.add_node("knowledge_validation", knowledge_validation)
    builder.add_node("ai_explanation", ai_explanation)
    builder.add_node("feedback_handler", feedback_handler)
    builder.add_node("escalation_handler", escalation_handler)
    builder.add_node("teacher_review", teacher_review)
    builder.add_node("persist_result", persist_result)
    builder.add_node("reject_result", reject_result)
    builder.add_edge(START, "context_builder")
    builder.add_edge("context_builder", "rule_engine")
    builder.add_edge("rule_engine", "fault_tree_analyzer")
    builder.add_edge("fault_tree_analyzer", "knowledge_context")
    builder.add_edge("knowledge_context", "ai_reasoning")
    builder.add_edge("ai_reasoning", "knowledge_validation")
    builder.add_conditional_edges(
        "knowledge_validation", route_after_knowledge_validation
    )
    builder.add_conditional_edges("ai_explanation", route_after_explanation)
    builder.add_edge("feedback_handler", "escalation_handler")
    builder.add_conditional_edges("escalation_handler", route_after_escalation)
    builder.add_conditional_edges("teacher_review", route_after_review)
    builder.add_edge("persist_result", END)
    builder.add_edge("reject_result", END)
    return builder.compile(checkpointer=checkpointer)
