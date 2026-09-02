"""Run a no-network acceptance check for the MVP structured knowledge path."""

from datetime import datetime, timezone

from langgraph.checkpoint.memory import InMemorySaver
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.ai.diagnosis_graph import build_diagnosis_graph
from app.db.base import Base
from app.diagnosis.workflow_schemas import DiagnosisState
from app.knowledge.loader import load_case_definitions
from app.knowledge.matcher import match_knowledge_cases
from app.models.diagnosis_result import DiagnosisResult
from app.models.knowledge import KnowledgeCase


def main() -> None:
    definitions = load_case_definitions()
    if len(definitions) != 5 or any(item.review_status != "pending" for item in definitions):
        raise SystemExit("external knowledge case validation failed")
    graph_nodes = set(build_diagnosis_graph(InMemorySaver()).get_graph().nodes)
    required_v2_nodes = {
        "context_builder",
        "rule_engine",
        "fault_tree_analyzer",
        "ai_reasoning",
        "knowledge_service",
        "ai_explanation",
        "feedback_handler",
        "escalation_handler",
    }
    if not required_v2_nodes.issubset(graph_nodes) or {
        "assess_evidence",
        "retrieve_knowledge",
    } & graph_nodes:
        raise SystemExit("diagnosis graph still contains a RAG branch")
    required_state_fields = {
        "device_status",
        "experiment_type",
        "logs",
        "sensor_data",
        "sensor_values",
        "experiment_context",
        "error_type",
        "evidence",
        "possible_causes",
        "knowledge_context",
        "hint_level",
        "student_feedback",
        "historical_failures",
        "attempt_count",
        "need_teacher_help",
        "diagnosis_status",
        "missing_evidence",
        "next_verification_action",
        "evidence_conflict",
        "evidence_registry",
        "allowed_verification_actions",
    }
    if not required_state_fields.issubset(DiagnosisState.__annotations__):
        raise SystemExit("DiagnosisState does not expose the complete V2 contract")

    engine = create_engine("sqlite+pysqlite://")
    Base.metadata.create_all(engine)
    try:
        with Session(engine) as db:
            source = definitions[0]
            values = source.model_dump(by_alias=False)
            values["review_status"] = "approved"
            values["is_test_data"] = True
            values["root_cause_value"] = values["possible_causes"][0]
            values["root_cause_status"] = "confirmed"
            values["confirmed_by"] = "verification-teacher"
            values["facts"] = {"source_ids": ["verification-evidence"]}
            values["solution_record"] = {"steps": values["solution_steps"]}
            values["source_type"] = "real_experiment"
            values["facts_locked"] = True
            values["quality_check_passed"] = True
            db.add(KnowledgeCase(**values))
            diagnosis = DiagnosisResult(
                device_id="structured-knowledge-verification-device",
                evaluated_at=datetime.now(timezone.utc),
                ruleset_version="verification",
                ruleset_hash="0" * 64,
                input_fingerprint="1" * 64,
                matched_rules=[
                    {
                        "error_type": source.error_type,
                        "summary": source.symptom,
                        "evidence": [{"fact": "log_event_count", "observed_value": 1}],
                    }
                ],
                evidence=[],
                context_snapshot={
                    "experiment_template": {"template_id": source.experiment_type},
                    "readings": [],
                },
                is_test_data=True,
            )
            db.add(diagnosis)
            db.commit()
            matched = match_knowledge_cases(db, diagnosis, [])
            if [item.case_id for item in matched] != [source.id]:
                raise SystemExit("structured knowledge matcher validation failed")
            print(
                {
                    "case_files": len(definitions),
                    "matched_case_id": matched[0].case_id,
                    "matched_on": matched[0].matched_on,
                    "graph_version": "langgraph-v2",
                    "state_fields": len(required_state_fields),
                    "ai_reasoning_constrained": "ai_reasoning" in graph_nodes,
                    "graph_has_structured_match": "knowledge_service" in graph_nodes,
                    "rag_enabled": False,
                }
            )
    finally:
        Base.metadata.drop_all(engine)
        engine.dispose()


if __name__ == "__main__":
    main()
