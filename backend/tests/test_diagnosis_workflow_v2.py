from langgraph.checkpoint.memory import InMemorySaver

from app.ai.diagnosis_graph import build_diagnosis_graph
from app.diagnosis.workflow_schemas import DiagnosisState

V2_NODES = {
    "context_builder",
    "rule_engine",
    "fault_tree_analyzer",
    "ai_reasoning",
    "knowledge_service",
    "ai_explanation",
    "feedback_handler",
    "escalation_handler",
}

V2_STATE_FIELDS = {
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
    "need_teacher_help",
    "diagnosis_status",
}


def test_v2_graph_exposes_controlled_diagnosis_nodes() -> None:
    graph = build_diagnosis_graph(InMemorySaver()).get_graph()

    assert V2_NODES.issubset(graph.nodes)
    assert {"assess_evidence", "retrieve_knowledge"}.isdisjoint(graph.nodes)


def test_v2_state_exposes_product_contract() -> None:
    assert V2_STATE_FIELDS.issubset(DiagnosisState.__annotations__)
