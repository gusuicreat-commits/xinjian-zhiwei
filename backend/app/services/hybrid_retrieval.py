from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.ai.clients import EmbeddingClient
from app.ai.schemas import AIKnowledgeReference
from app.core.config import Settings
from app.models.knowledge import KnowledgeChunk, KnowledgeDocument, KnowledgeSource
from app.schemas.knowledge import KnowledgeSearchRequest
from app.services.knowledge import search_knowledge


@dataclass(frozen=True)
class HybridRetrievalResult:
    references: list[AIKnowledgeReference]
    lexical_used: bool
    vector_used: bool
    retrieval_conflict: bool = False


def _tokens(value: str) -> set[str]:
    return {
        token.lower()
        for token in re.findall(r"[A-Za-z0-9_]{2,}|[\u4e00-\u9fff]{2,}", value)
    }


def _lexical_rows(
    db: Session,
    query: str,
    *,
    limit: int,
    include_test_data: bool,
    metadata_filters: dict[str, Any],
) -> list[tuple[KnowledgeChunk, KnowledgeDocument, KnowledgeSource, float]]:
    base = (
        select(KnowledgeChunk, KnowledgeDocument, KnowledgeSource)
        .join(KnowledgeDocument, KnowledgeDocument.id == KnowledgeChunk.document_id)
        .join(KnowledgeSource, KnowledgeSource.id == KnowledgeDocument.source_id)
        .where(
            KnowledgeChunk.review_status == "approved",
            KnowledgeDocument.review_status == "approved",
        )
    )
    if not include_test_data:
        base = base.where(
            KnowledgeDocument.is_test_data.is_(False),
            KnowledgeSource.is_test_data.is_(False),
        )
    source_types = metadata_filters.get("source_types") or []
    if source_types:
        base = base.where(KnowledgeSource.source_type.in_(source_types))
    dialect = db.get_bind().dialect.name
    if dialect == "postgresql":
        vector = func.to_tsvector("simple", KnowledgeChunk.content)
        tsquery = func.plainto_tsquery("simple", query)
        rank = func.ts_rank_cd(vector, tsquery)
        rows = db.execute(
            base.add_columns(rank.label("lexical_rank"))
            .where(vector.op("@@")(tsquery))
            .order_by(rank.desc())
            .limit(limit)
        ).all()
        return [
            (row[0], row[1], row[2], float(row[3] or 0.0))
            for row in rows
            if _metadata_matches(row[0].metadata_json, metadata_filters)
        ]
    query_tokens = _tokens(query)
    candidates = db.execute(base.limit(max(limit * 20, 100))).all()
    ranked = []
    for chunk, document, source in candidates:
        if not _metadata_matches(chunk.metadata_json, metadata_filters):
            continue
        overlap = query_tokens.intersection(_tokens(chunk.content))
        if overlap:
            ranked.append((chunk, document, source, len(overlap) / max(1, len(query_tokens))))
    ranked.sort(key=lambda item: (-item[3], item[0].id))
    return ranked[:limit]


def _metadata_matches(metadata: dict[str, Any], filters: dict[str, Any]) -> bool:
    for key, expected in filters.items():
        if key == "source_types" or expected in (None, "", []):
            continue
        actual = metadata.get(key)
        if isinstance(expected, list):
            if actual not in expected:
                return False
        elif actual != expected:
            return False
    return True


def hybrid_retrieve(
    db: Session,
    query: str,
    settings: Settings,
    embedding_client: EmbeddingClient,
    *,
    include_test_data: bool,
    metadata_filters: dict[str, Any] | None = None,
) -> HybridRetrievalResult:
    filters = metadata_filters or {}
    lexical = _lexical_rows(
        db,
        query,
        limit=settings.rag_lexical_top_n,
        include_test_data=include_test_data,
        metadata_filters=filters,
    )
    items: dict[str, tuple[AIKnowledgeReference, float]] = {}
    for rank, (chunk, document, source, lexical_score) in enumerate(lexical, 1):
        reference = AIKnowledgeReference(
            chunk_id=chunk.id,
            source_key=source.source_key,
            source_title=source.title,
            source_uri=source.source_uri,
            source_version=source.version,
            locator=chunk.locator_json,
            content=chunk.content,
            similarity=lexical_score,
            retrieval_scores={"lexical": lexical_score},
            is_test_data=document.is_test_data or source.is_test_data,
        )
        items[chunk.id] = (reference, 1.0 / (settings.rag_rrf_k + rank))

    vector_used = False
    if embedding_client.configured and query:
        vector = embedding_client.embed(query)
        response = search_knowledge(
            db,
            KnowledgeSearchRequest(
                query_embedding=vector,
                provider=embedding_client.provider,
                model=embedding_client.model,
                limit=settings.rag_vector_top_n,
                source_types=list(filters.get("source_types") or []),
                include_test_data=include_test_data,
            ),
        )
        vector_used = True
        for rank, result in enumerate(response.results, 1):
            if result.similarity <= 0:
                continue
            chunk = db.get(KnowledgeChunk, result.chunk_id)
            if chunk is None or not _metadata_matches(chunk.metadata_json, filters):
                continue
            existing = items.get(result.chunk_id)
            reference = AIKnowledgeReference(
                chunk_id=result.chunk_id,
                source_key=result.source_key,
                source_title=result.source_title,
                source_uri=result.source_uri,
                source_version=result.source_version,
                locator=result.locator,
                content=result.content,
                similarity=result.similarity,
                retrieval_scores={"vector": result.similarity},
                is_test_data=result.is_test_data,
            )
            score = 1.0 / (settings.rag_rrf_k + rank)
            if existing:
                combined_scores = dict(existing[0].retrieval_scores)
                combined_scores["vector"] = result.similarity
                reference = existing[0].model_copy(
                    update={"retrieval_scores": combined_scores}
                )
            items[result.chunk_id] = (reference, score + (existing[1] if existing else 0.0))
    ranked = sorted(items.values(), key=lambda item: (-item[1], item[0].chunk_id))
    references = [
        reference.model_copy(
            update={
                "similarity": score,
                "retrieval_scores": {
                    **reference.retrieval_scores,
                    "rrf": score,
                },
            }
        )
        for reference, score in ranked[: settings.rag_fused_top_k]
    ]
    return HybridRetrievalResult(
        references=references,
        lexical_used=True,
        vector_used=vector_used,
    )
