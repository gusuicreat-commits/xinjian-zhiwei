from __future__ import annotations

from typing import Any

from langchain_core.tools import BaseTool, tool
from sqlalchemy.orm import Session

from app.ai.clients import EmbeddingClient
from app.core.config import Settings
from app.diagnosis.fault_tree_loader import load_fault_trees
from app.diagnosis.loader import load_rules
from app.services.hybrid_retrieval import hybrid_retrieve


def build_read_only_diagnosis_tools(
    db: Session,
    settings: Settings,
    embedding_client: EmbeddingClient,
    *,
    include_test_data: bool,
) -> list[BaseTool]:
    """Build the deliberately narrow LangChain tool allowlist.

    These tools can only read rules, fault-tree definitions, and approved knowledge.
    No generic SQL, shell, HTTP, device-control, or database-write tool is exposed.
    """

    @tool
    def search_approved_fault_knowledge(
        query: str,
        device_family: str | None = None,
        error_code: str | None = None,
        experiment: str | None = None,
    ) -> list[dict[str, Any]]:
        """Search teacher-approved fault knowledge using constrained metadata filters."""
        filters = {
            key: value
            for key, value in {
                "device_family": device_family,
                "error_code": error_code,
                "experiment": experiment,
            }.items()
            if value
        }
        result = hybrid_retrieve(
            db,
            query,
            settings,
            embedding_client,
            include_test_data=include_test_data,
            metadata_filters=filters,
        )
        return [item.model_dump(mode="json") for item in result.references]

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
