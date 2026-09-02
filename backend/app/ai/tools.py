from __future__ import annotations

from typing import Any

from langchain_core.tools import BaseTool, tool
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.diagnosis.fault_tree_loader import load_fault_trees
from app.diagnosis.loader import load_rules
from app.models.knowledge import KnowledgeCase


def build_read_only_diagnosis_tools(
    db: Session,
    settings: Settings,
    embedding_client: Any = None,
    *,
    include_test_data: bool,
) -> list[BaseTool]:
    """Build the deliberately narrow LangChain tool allowlist.

    These tools can only read rules, fault-tree definitions, and approved knowledge.
    No generic SQL, shell, HTTP, device-control, or database-write tool is exposed.
    """

    del settings, embedding_client

    @tool
    def search_approved_fault_knowledge(
        query: str,
        device_family: str | None = None,
        error_code: str | None = None,
        experiment: str | None = None,
    ) -> list[dict[str, Any]]:
        """Match approved structured cases using explicit fields only."""
        del query, device_family
        statement = select(KnowledgeCase).where(KnowledgeCase.review_status == "approved")
        if error_code:
            statement = statement.where(KnowledgeCase.error_type == error_code)
        if experiment:
            statement = statement.where(KnowledgeCase.experiment_type == experiment)
        if not include_test_data:
            statement = statement.where(KnowledgeCase.is_test_data.is_(False))
        cases = list(db.scalars(statement.order_by(KnowledgeCase.id).limit(20)))
        return [
            {
                "case_id": item.id,
                "experiment_type": item.experiment_type,
                "error_type": item.error_type,
                "symptom": item.symptom,
                "evidence": item.evidence,
                "possible_causes": item.possible_causes,
                "solution_steps": item.solution_steps,
                "teacher_notes": item.teacher_notes,
                "source_ref": item.source_ref,
                "version": item.version,
            }
            for item in cases
        ]

    @tool
    def get_rule_explanation(rule_id: str) -> dict[str, Any]:
        """Return one configured deterministic rule definition by its exact ID."""
        rules, _ = load_rules()
        match = next((item for item in rules.rules if item.id == rule_id), None)
        return match.model_dump(mode="json") if match is not None else {}

    @tool
    def get_fault_tree_path(cause_id: str) -> dict[str, Any]:
        """Return one configured fault-tree cause and its fixed hint path."""
        trees, _ = load_fault_trees()
        for tree in trees.trees:
            cause = next((item for item in tree.causes if item.id == cause_id), None)
            if cause is not None:
                return {
                    "tree_id": tree.id,
                    "tree_version": trees.version,
                    "tree_status": tree.status,
                    "cause": cause.model_dump(mode="json"),
                }
        return {}

    return [
        search_approved_fault_knowledge,
        get_rule_explanation,
        get_fault_tree_path,
    ]
