"""Removed MVP RAG facade.

The first MVP uses ``app.knowledge.matcher.match_knowledge_cases``.  This small
compatibility module keeps older maintenance scripts importable while making it
impossible to execute lexical, vector, or fused retrieval by accident.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.ai.schemas import AIKnowledgeReference


@dataclass(frozen=True)
class HybridRetrievalResponse:
    references: list[AIKnowledgeReference]
    lexical_count: int = 0
    vector_used: bool = False


def hybrid_retrieve(*args: Any, **kwargs: Any) -> HybridRetrievalResponse:
    del args, kwargs
    raise RuntimeError(
        "RAG retrieval is outside the MVP; use deterministic structured knowledge matching"
    )
