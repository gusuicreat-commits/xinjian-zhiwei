from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from functools import wraps
from time import perf_counter
from typing import Any, Literal

from langchain_core.runnables import RunnableLambda
from langgraph.graph import END, START, StateGraph
from langgraph.runtime import Runtime
from langgraph.types import interrupt
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.clients import (
    AIClient,
    EmbeddingClient,
    build_embedding_client,
)
from app.ai.context_sanitizer import sanitize_text
from app.ai.schemas import AIExplanationResponse, AIKnowledgeReference
from app.core.config import Settings
from app.diagnosis.schemas import DiagnosisOutcome, ExperimentTemplateContext
from app.diagnosis.workflow_schemas import DiagnosisState
from app.models.base import utc_now
from app.models.classroom import ExperimentSession
from app.models.device import Device
from app.models.diagnosis_result import DiagnosisResult
from app.models.diagnosis_workflow import DiagnosisWorkflowReview, DiagnosisWorkflowRun
from app.models.guidance_history import GuidanceHistory
from app.models.knowledge import KnowledgeChunk, KnowledgeDocument, KnowledgeSource
from app.services.ai_diagnosis import _retrieve_knowledge, explain_diagnosis
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
    embedding_client: EmbeddingClient | None = None
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


@observed_node("collect_context")
def collect_context(
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
    )
    # Checkpoints retain a bounded context snapshot, not full historical tables.
    return {
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
        "node_trace": ["collect_context"],
    }


@observed_node("run_rules")
def run_rules(state: DiagnosisState, runtime: Runtime[DiagnosisGraphContext]) -> dict[str, Any]:
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
    return {
        "diagnosis_result_id": record.id,
        "rule_hits": [
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
        ],
        "rule_engine_version": outcome.ruleset_version,
        "rule_engine_hash": outcome.ruleset_hash,
        "input_fingerprint": outcome.input_fingerprint,
        "node_trace": ["run_rules"],
    }


@observed_node("run_fault_tree")
def run_fault_tree(
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
    return {
        "fault_tree_candidates": candidates,
        "fault_tree_version": guidance[0].fault_tree_version if guidance else "none",
        "evidence_score": core.confidence,
        "guidance_level": core.hint_level,
        "deterministic_result": deterministic.model_dump(mode="json"),
        "node_trace": ["run_fault_tree"],
    }


@observed_node("assess_evidence")
def assess_evidence(
    state: DiagnosisState, runtime: Runtime[DiagnosisGraphContext]
) -> dict[str, Any]:
    needs_rag = (
        state.get("evidence_score", 0.0) < runtime.context.settings.diagnosis_rag_trigger_score
    )
    return {
        "needs_rag": needs_rag,
        "node_trace": ["assess_evidence"],
    }


def route_after_assessment(
    state: DiagnosisState,
) -> Literal["retrieve_knowledge", "explain_for_student"]:
    return "retrieve_knowledge" if state.get("needs_rag") else "explain_for_student"


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
}
_RETRIEVAL_SCORE_KEYS = {"lexical", "vector", "rrf"}


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
    rows = runtime.context.db.execute(
        select(KnowledgeChunk, KnowledgeDocument, KnowledgeSource)
        .join(KnowledgeDocument, KnowledgeDocument.id == KnowledgeChunk.document_id)
        .join(KnowledgeSource, KnowledgeSource.id == KnowledgeDocument.source_id)
        .where(
            KnowledgeChunk.id.in_(chunk_ids),
            KnowledgeChunk.review_status == "approved",
            KnowledgeDocument.review_status == "approved",
        )
    ).all()
    by_id = {chunk.id: (chunk, document, source) for chunk, document, source in rows}
    references: list[AIKnowledgeReference] = []
    safe_state_refs: list[dict[str, Any]] = []
    for state_item in requested:
        row = by_id.get(str(state_item["chunk_id"]))
        if row is None:
            continue
        chunk, document, source = row
        metadata = state_item.get("metadata") or {}
        reference = AIKnowledgeReference(
            chunk_id=chunk.id,
            source_key=source.source_key,
            source_title=source.title,
            source_type=source.source_type,
            source_uri=None,
            source_version=source.version,
            locator=chunk.locator_json,
            content=chunk.content,
            similarity=float(state_item.get("score") or 0.0),
            review_status="approved",
            retrieval_scores={
                key: float(value)
                for key, value in (metadata.get("retrieval_scores") or {}).items()
                if key in _RETRIEVAL_SCORE_KEYS and isinstance(value, (int, float))
            },
            is_test_data=document.is_test_data or source.is_test_data,
        )
        references.append(reference)
        safe_state_refs.append(_knowledge_state_reference(reference))
    return _safe_graph_knowledge(references, runtime.context.settings), safe_state_refs


@observed_node("retrieve_knowledge")
def retrieve_knowledge(
    state: DiagnosisState, runtime: Runtime[DiagnosisGraphContext]
) -> dict[str, Any]:
    diagnosis = _diagnosis(runtime, state)
    guidance = _guidance(runtime, state)
    embedding = runtime.context.embedding_client or build_embedding_client(runtime.context.settings)
    query = _retrieval_query(state)
    references = _retrieve_knowledge(
        runtime.context.db,
        diagnosis,
        guidance,
        runtime.context.settings,
        embedding,
        query_override=query,
    )
    return {
        "retrieval_query": query,
        "retrieved_chunks": [_knowledge_state_reference(item) for item in references],
        "status": "retrieving",
        "node_trace": ["retrieve_knowledge"],
    }


@observed_node("explain_for_student")
def explain_for_student(
    state: DiagnosisState, runtime: Runtime[DiagnosisGraphContext]
) -> dict[str, Any]:
    diagnosis = _diagnosis(runtime, state)
    graph_knowledge, safe_state_refs = _load_graph_knowledge(state, runtime)

    # LangChain is the capability adapter; the existing governed provider client,
    # privacy sanitizer, cache, budgets and strict Pydantic validation stay intact.
    chain = RunnableLambda(
        lambda evidence_package: explain_diagnosis(
            runtime.context.db,
            runtime.context.device,
            diagnosis,
            runtime.context.settings,
            ai_client=runtime.context.ai_client,
            ai_clients=runtime.context.ai_clients,
            embedding_client=runtime.context.embedding_client,
            user_question=evidence_package.get("question"),
            # An empty list is deliberate: LangGraph is the sole retrieval control
            # plane, so the legacy service must never perform a hidden second RAG.
            retrieved_knowledge=graph_knowledge,
            workflow_run_id=state["diagnosis_id"],
        )
    ).with_config({"run_name": "xinjian_safe_structured_diagnosis"})
    response: AIExplanationResponse = chain.invoke(
        {
            "question": state.get("question"),
            "rule_hits": state.get("rule_hits", []),
            "fault_tree_candidates": state.get("fault_tree_candidates", []),
            "retrieved_chunk_ids": [item["chunk_id"] for item in state.get("retrieved_chunks", [])],
        }
    )
    return {
        "ai_result": (
            response.explanation.model_dump(mode="json") if response.explanation else None
        ),
        "retrieved_chunks": safe_state_refs,
        "model_id": runtime.context.settings.ai_model,
        "status": "ai_analysis",
        "node_trace": ["explain_for_student"],
    }


@observed_node("approval_gate")
def approval_gate(state: DiagnosisState, runtime: Runtime[DiagnosisGraphContext]) -> dict[str, Any]:
    score = state.get("evidence_score", 0.0)
    no_rag_evidence = bool(state.get("needs_rag") and not state.get("retrieved_chunks"))
    ai_conflicts_with_rules = bool(
        state.get("ai_result")
        and state.get("rule_hits")
        and state["ai_result"].get("error_type")
        not in {item["error_type"] for item in state["rule_hits"]}
    )
    needs_teacher = (
        state.get("guidance_level", 1) >= 4
        or score < runtime.context.settings.diagnosis_teacher_review_score
        or no_rag_evidence
        or ai_conflicts_with_rules
    )
    return {
        "needs_teacher": needs_teacher,
        "status": "waiting_teacher" if needs_teacher else "completed",
        "node_trace": ["approval_gate"],
    }


def route_after_gate(
    state: DiagnosisState,
) -> Literal["teacher_review", "persist_result"]:
    return "teacher_review" if state.get("needs_teacher") else "persist_result"


def teacher_review(state: DiagnosisState) -> dict[str, Any]:
    decision = interrupt(
        {
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
    base["evidence_score"] = state.get("evidence_score")
    base["guidance_level"] = state.get("guidance_level")
    base["teacher_reviewed"] = bool(review)
    base["candidate_causes"] = state.get("fault_tree_candidates", [])
    base["knowledge_references"] = [
        {
            "chunk_id": item.get("chunk_id"),
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
    return {"status": "rejected", "node_trace": ["reject_result"]}


def build_diagnosis_graph(checkpointer: Any):
    builder = StateGraph(DiagnosisState, context_schema=DiagnosisGraphContext)
    builder.add_node("collect_context", collect_context)
    builder.add_node("run_rules", run_rules)
    builder.add_node("run_fault_tree", run_fault_tree)
    builder.add_node("assess_evidence", assess_evidence)
    builder.add_node("retrieve_knowledge", retrieve_knowledge)
    builder.add_node("explain_for_student", explain_for_student)
    builder.add_node("approval_gate", approval_gate)
    builder.add_node("teacher_review", teacher_review)
    builder.add_node("persist_result", persist_result)
    builder.add_node("reject_result", reject_result)
    builder.add_edge(START, "collect_context")
    builder.add_edge("collect_context", "run_rules")
    builder.add_edge("run_rules", "run_fault_tree")
    builder.add_edge("run_fault_tree", "assess_evidence")
    builder.add_conditional_edges("assess_evidence", route_after_assessment)
    builder.add_edge("retrieve_knowledge", "explain_for_student")
    builder.add_edge("explain_for_student", "approval_gate")
    builder.add_conditional_edges("approval_gate", route_after_gate)
    builder.add_conditional_edges("teacher_review", route_after_review)
    builder.add_edge("persist_result", END)
    builder.add_edge("reject_result", END)
    return builder.compile(checkpointer=checkpointer)
