import hashlib
import math
from dataclasses import dataclass
from typing import Any

from sqlalchemy import Float, cast, func, literal, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload, selectinload

from app.core.config import Settings
from app.db.vector import PortableVector
from app.models.knowledge import (
    KnowledgeChunk,
    KnowledgeDocument,
    KnowledgeEmbedding,
    KnowledgeReview,
    KnowledgeSource,
)
from app.schemas.knowledge import (
    KnowledgeChunkResponse,
    KnowledgeDocumentResponse,
    KnowledgeEmbeddingUpsertRequest,
    KnowledgeEmbeddingUpsertResponse,
    KnowledgeReviewRequest,
    KnowledgeReviewResponse,
    KnowledgeSearchRequest,
    KnowledgeSearchResponse,
    KnowledgeSearchResult,
    KnowledgeSourceCreate,
    KnowledgeSourceResponse,
    KnowledgeStatusResponse,
    KnowledgeTextImportRequest,
)

FORMAL_SOURCE_TYPES = {
    "official_hardware",
    "course_material",
    "confirmed_parameter",
    "verified_case",
    "supplementary",
}
ROOT_CAUSE_CONFIDENCE = {"confirmed", "high", "medium", "low", "unknown"}
REVIEW_TRANSITIONS = {
    ("draft", "pending"): "organizer",
    ("pending", "technical_reviewed"): "technical_reviewer",
    ("pending", "rejected"): "technical_reviewer",
    ("technical_reviewed", "approved"): "formal_approver",
    ("technical_reviewed", "rejected"): "formal_approver",
    ("approved", "withdrawn"): "formal_approver",
    ("approved", "superseded"): "formal_approver",
    ("rejected", "draft"): "organizer",
    ("withdrawn", "draft"): "organizer",
    ("superseded", "draft"): "organizer",
}


@dataclass
class KnowledgeServiceError(Exception):
    status_code: int
    code: str
    message: str


def _hash_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _normalize_text(value: str) -> str:
    lines = [line.rstrip() for line in value.replace("\r\n", "\n").replace("\r", "\n").split("\n")]
    return "\n".join(lines).strip()


def split_text(content: str, chunk_size: int, overlap: int) -> list[tuple[str, int, int]]:
    if overlap >= chunk_size:
        raise KnowledgeServiceError(
            500,
            "INVALID_CHUNK_CONFIGURATION",
            "Knowledge chunk overlap must be smaller than chunk size",
        )
    chunks: list[tuple[str, int, int]] = []
    start = 0
    length = len(content)
    while start < length:
        proposed_end = min(start + chunk_size, length)
        end = proposed_end
        if proposed_end < length:
            minimum_break = start + max(1, int(chunk_size * 0.6))
            newline_break = content.rfind("\n", minimum_break, proposed_end)
            space_break = content.rfind(" ", minimum_break, proposed_end)
            candidate = max(newline_break, space_break)
            if candidate > start:
                end = candidate
        chunk = content[start:end].strip()
        if chunk:
            chunks.append((chunk, start, end))
        if end >= length:
            break
        start = max(end - overlap, start + 1)
    return chunks


def _source_response(source: KnowledgeSource) -> KnowledgeSourceResponse:
    return KnowledgeSourceResponse(
        id=source.id,
        source_key=source.source_key,
        source_type=source.source_type,
        title=source.title,
        source_uri=source.source_uri,
        version=source.version,
        license_name=source.license_name,
        authorization_scope=source.authorization_scope,
        metadata=source.metadata_json,
        is_test_data=source.is_test_data,
        created_at=source.created_at,
        updated_at=source.updated_at,
    )


def _document_response(
    document: KnowledgeDocument, *, idempotent_replay: bool = False
) -> KnowledgeDocumentResponse:
    return KnowledgeDocumentResponse(
        id=document.id,
        source_id=document.source_id,
        title=document.title,
        media_type=document.media_type,
        language=document.language,
        storage_uri=document.storage_uri,
        content_hash=document.content_hash,
        parser_name=document.parser_name,
        parser_version=document.parser_version,
        review_status=document.review_status,
        is_test_data=document.is_test_data,
        created_at=document.created_at,
        updated_at=document.updated_at,
        chunks=[
            KnowledgeChunkResponse(
                id=chunk.id,
                chunk_index=chunk.chunk_index,
                content_hash=chunk.content_hash,
                char_count=chunk.char_count,
                locator=chunk.locator_json,
                metadata=chunk.metadata_json,
                review_status=chunk.review_status,
            )
            for chunk in sorted(document.chunks, key=lambda item: item.chunk_index)
        ],
        idempotent_replay=idempotent_replay,
    )


def create_source(db: Session, payload: KnowledgeSourceCreate) -> KnowledgeSourceResponse:
    if not payload.is_test_data:
        if payload.source_type not in FORMAL_SOURCE_TYPES:
            raise KnowledgeServiceError(
                422,
                "INVALID_FORMAL_SOURCE_TYPE",
                "Formal knowledge must use a governed source type",
            )
        if not payload.source_uri or not payload.version:
            raise KnowledgeServiceError(
                422,
                "FORMAL_SOURCE_TRACEABILITY_REQUIRED",
                "Formal knowledge sources require both source_uri and version",
            )
    source = KnowledgeSource(
        source_key=payload.source_key,
        source_type=payload.source_type,
        title=payload.title,
        source_uri=payload.source_uri,
        version=payload.version,
        license_name=payload.license_name,
        authorization_scope=payload.authorization_scope,
        metadata_json=payload.metadata,
        is_test_data=payload.is_test_data,
    )
    db.add(source)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise KnowledgeServiceError(
            409, "KNOWLEDGE_SOURCE_EXISTS", "Knowledge source key already exists"
        ) from exc
    db.refresh(source)
    return _source_response(source)


def list_sources(db: Session) -> list[KnowledgeSourceResponse]:
    sources = db.scalars(select(KnowledgeSource).order_by(KnowledgeSource.created_at.desc())).all()
    return [_source_response(source) for source in sources]


def import_text_document(
    db: Session,
    source_id: str,
    payload: KnowledgeTextImportRequest,
    settings: Settings,
) -> KnowledgeDocumentResponse:
    source = db.get(KnowledgeSource, source_id)
    if source is None:
        raise KnowledgeServiceError(404, "KNOWLEDGE_SOURCE_NOT_FOUND", "Knowledge source not found")
    if not payload.media_type.startswith("text/"):
        raise KnowledgeServiceError(
            422,
            "UNSUPPORTED_KNOWLEDGE_MEDIA_TYPE",
            "The generic importer accepts extracted text only",
        )
    content = _normalize_text(payload.content)
    if not content:
        raise KnowledgeServiceError(422, "EMPTY_KNOWLEDGE_DOCUMENT", "Document text is empty")
    if len(content) > settings.knowledge_max_document_chars:
        raise KnowledgeServiceError(
            413,
            "KNOWLEDGE_DOCUMENT_TOO_LARGE",
            "Document text exceeds the configured character limit",
        )
    document_is_test = source.is_test_data or payload.is_test_data
    if not document_is_test:
        if not payload.organizer_ref:
            raise KnowledgeServiceError(
                422,
                "KNOWLEDGE_ORGANIZER_REQUIRED",
                "Formal knowledge requires a traceable organizer_ref",
            )
        if not payload.metadata.get("applicable_hardware"):
            raise KnowledgeServiceError(
                422,
                "APPLICABLE_HARDWARE_REQUIRED",
                "Formal knowledge must declare applicable_hardware",
            )
        if source.source_type == "official_hardware" and not (
            payload.locator_prefix.get("page")
            or payload.locator_prefix.get("section")
            or payload.locator_prefix.get("chapter")
        ):
            raise KnowledgeServiceError(
                422,
                "OFFICIAL_SOURCE_LOCATOR_REQUIRED",
                "Official hardware material requires a page, section or chapter locator",
            )
        if source.source_type == "verified_case":
            confidence = payload.metadata.get("root_cause_confidence")
            if not payload.metadata.get("final_fix_action"):
                raise KnowledgeServiceError(
                    422,
                    "FINAL_FIX_ACTION_REQUIRED",
                    "Verified cases must record final_fix_action",
                )
            if confidence not in ROOT_CAUSE_CONFIDENCE:
                raise KnowledgeServiceError(
                    422,
                    "ROOT_CAUSE_CONFIDENCE_REQUIRED",
                    "Verified cases require a governed root_cause_confidence",
                )
    content_hash = _hash_text(content)
    existing = db.scalar(
        select(KnowledgeDocument)
        .where(
            KnowledgeDocument.source_id == source.id,
            KnowledgeDocument.content_hash == content_hash,
        )
        .options(selectinload(KnowledgeDocument.chunks))
    )
    if existing is not None:
        return _document_response(existing, idempotent_replay=True)

    chunk_values = split_text(
        content,
        settings.knowledge_chunk_size_chars,
        settings.knowledge_chunk_overlap_chars,
    )
    document = KnowledgeDocument(
        source_id=source.id,
        title=payload.title,
        media_type=payload.media_type,
        language=payload.language,
        storage_uri=payload.storage_uri,
        content_hash=content_hash,
        parser_name=payload.parser_name,
        parser_version=payload.parser_version,
        review_status="draft",
        is_test_data=document_is_test,
    )
    db.add(document)
    db.flush()
    for index, (chunk_text, start, end) in enumerate(chunk_values):
        locator = dict(payload.locator_prefix)
        locator.update({"chunk_index": index, "start_char": start, "end_char": end})
        db.add(
            KnowledgeChunk(
                document_id=document.id,
                chunk_index=index,
                content=chunk_text,
                content_hash=_hash_text(chunk_text),
                char_count=len(chunk_text),
                locator_json=locator,
                metadata_json={
                    **payload.metadata,
                    "organizer_ref": payload.organizer_ref,
                    "content_origin": payload.content_origin,
                },
            )
        )
    db.commit()
    document = db.scalar(
        select(KnowledgeDocument)
        .where(KnowledgeDocument.id == document.id)
        .options(selectinload(KnowledgeDocument.chunks))
    )
    if document is None:
        raise KnowledgeServiceError(
            500, "KNOWLEDGE_IMPORT_FAILED", "Imported document was not found"
        )
    return _document_response(document)


def review_document(
    db: Session, document_id: str, payload: KnowledgeReviewRequest
) -> KnowledgeReviewResponse:
    document = db.scalar(
        select(KnowledgeDocument)
        .where(KnowledgeDocument.id == document_id)
        .options(
            joinedload(KnowledgeDocument.source),
            selectinload(KnowledgeDocument.chunks),
            selectinload(KnowledgeDocument.reviews),
        )
    )
    if document is None:
        raise KnowledgeServiceError(
            404, "KNOWLEDGE_DOCUMENT_NOT_FOUND", "Knowledge document not found"
        )
    required_role = REVIEW_TRANSITIONS.get(
        (document.review_status, payload.decision)
    )
    if required_role is None:
        raise KnowledgeServiceError(
            409,
            "INVALID_KNOWLEDGE_REVIEW_TRANSITION",
            f"Cannot transition from {document.review_status} to {payload.decision}",
        )
    if payload.reviewer_role != required_role:
        raise KnowledgeServiceError(
            403,
            "KNOWLEDGE_REVIEW_ROLE_MISMATCH",
            f"Transition requires reviewer role {required_role}",
        )
    metadata = document.chunks[0].metadata_json if document.chunks else {}
    organizer_ref = metadata.get("organizer_ref")
    if (
        payload.reviewer_role in {"technical_reviewer", "formal_approver"}
        and organizer_ref
        and payload.reviewer_ref == organizer_ref
    ):
        raise KnowledgeServiceError(
            409,
            "KNOWLEDGE_SELF_REVIEW_FORBIDDEN",
            "The organizer cannot perform technical or formal review",
        )
    if payload.reviewer_role == "formal_approver":
        technical_reviewers = {
            review.reviewer_ref
            for review in document.reviews
            if review.reviewer_role == "technical_reviewer"
        }
        if payload.reviewer_ref in technical_reviewers:
            raise KnowledgeServiceError(
                409,
                "KNOWLEDGE_REVIEW_SEPARATION_REQUIRED",
                "The formal approver must differ from the technical reviewer",
            )
    if payload.decision == "approved" and not document.source.authorization_scope:
        raise KnowledgeServiceError(
            409,
            "KNOWLEDGE_AUTHORIZATION_REQUIRED",
            "Authorization scope must be recorded before approval",
        )
    document.review_status = payload.decision
    for chunk in document.chunks:
        chunk.review_status = payload.decision
    review = KnowledgeReview(
        document_id=document.id,
        decision=payload.decision,
        reviewer_role=payload.reviewer_role,
        reviewer_ref=payload.reviewer_ref,
        note=payload.note,
    )
    db.add(review)
    db.commit()
    db.refresh(review)
    return KnowledgeReviewResponse(
        document_id=document.id,
        decision=payload.decision,
        reviewer_role=payload.reviewer_role,
        reviewer_ref=payload.reviewer_ref,
        reviewed_at=review.created_at,
        affected_chunks=len(document.chunks),
    )


def upsert_embeddings(
    db: Session,
    document_id: str,
    payload: KnowledgeEmbeddingUpsertRequest,
    settings: Settings,
) -> KnowledgeEmbeddingUpsertResponse:
    document = db.scalar(
        select(KnowledgeDocument)
        .where(KnowledgeDocument.id == document_id)
        .options(selectinload(KnowledgeDocument.chunks))
    )
    if document is None:
        raise KnowledgeServiceError(
            404, "KNOWLEDGE_DOCUMENT_NOT_FOUND", "Knowledge document not found"
        )
    if document.review_status != "approved":
        raise KnowledgeServiceError(
            409, "KNOWLEDGE_DOCUMENT_NOT_APPROVED", "Document must be approved before embedding"
        )
    dimensions = len(payload.items[0].vector)
    if any(len(item.vector) != dimensions for item in payload.items):
        raise KnowledgeServiceError(
            422, "INCONSISTENT_EMBEDDING_DIMENSIONS", "All vectors must have equal dimensions"
        )
    if settings.knowledge_embedding_configured:
        if (
            payload.provider != settings.knowledge_embedding_provider
            or payload.model != settings.knowledge_embedding_model
            or dimensions != settings.knowledge_embedding_dimensions
        ):
            raise KnowledgeServiceError(
                409,
                "EMBEDDING_CONFIGURATION_MISMATCH",
                "Embedding payload does not match the configured provider, model and dimensions",
            )
    elif not payload.is_test_data:
        raise KnowledgeServiceError(
            503,
            "EMBEDDING_PROVIDER_NOT_CONFIGURED",
            "Only explicitly marked test vectors are accepted until an embedding provider "
            "is configured",
        )

    chunks = {chunk.id: chunk for chunk in document.chunks}
    requested_ids = [item.chunk_id for item in payload.items]
    if len(set(requested_ids)) != len(requested_ids) or any(
        chunk_id not in chunks for chunk_id in requested_ids
    ):
        raise KnowledgeServiceError(
            422,
            "INVALID_EMBEDDING_CHUNK",
            "Embedding items must reference unique chunks from the requested document",
        )
    for item in payload.items:
        existing = db.scalar(
            select(KnowledgeEmbedding).where(
                KnowledgeEmbedding.chunk_id == item.chunk_id,
                KnowledgeEmbedding.provider == payload.provider,
                KnowledgeEmbedding.model == payload.model,
            )
        )
        if existing is None:
            db.add(
                KnowledgeEmbedding(
                    chunk_id=item.chunk_id,
                    provider=payload.provider,
                    model=payload.model,
                    dimensions=dimensions,
                    embedding=item.vector,
                    is_test_data=document.is_test_data or payload.is_test_data,
                )
            )
        else:
            existing.dimensions = dimensions
            existing.embedding = item.vector
            existing.is_test_data = document.is_test_data or payload.is_test_data
    db.commit()
    return KnowledgeEmbeddingUpsertResponse(
        provider=payload.provider,
        model=payload.model,
        dimensions=dimensions,
        stored_count=len(payload.items),
    )


def _cosine_similarity(left: list[float], right: list[float]) -> float:
    numerator = sum(a * b for a, b in zip(left, right))
    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))
    return numerator / (left_norm * right_norm)


def search_knowledge(db: Session, payload: KnowledgeSearchRequest) -> KnowledgeSearchResponse:
    conditions = [
        KnowledgeEmbedding.provider == payload.provider,
        KnowledgeEmbedding.model == payload.model,
        KnowledgeEmbedding.dimensions == len(payload.query_embedding),
        KnowledgeChunk.review_status == "approved",
        KnowledgeDocument.review_status == "approved",
    ]
    if payload.source_types:
        conditions.append(KnowledgeSource.source_type.in_(payload.source_types))
    if not payload.include_test_data:
        conditions.extend(
            [
                KnowledgeSource.is_test_data.is_(False),
                KnowledgeDocument.is_test_data.is_(False),
                KnowledgeEmbedding.is_test_data.is_(False),
            ]
        )

    base = (
        select(KnowledgeEmbedding, KnowledgeChunk, KnowledgeDocument, KnowledgeSource)
        .join(KnowledgeChunk, KnowledgeEmbedding.chunk_id == KnowledgeChunk.id)
        .join(KnowledgeDocument, KnowledgeChunk.document_id == KnowledgeDocument.id)
        .join(KnowledgeSource, KnowledgeDocument.source_id == KnowledgeSource.id)
        .where(*conditions)
    )
    rows: list[tuple[Any, ...]]
    dialect_name = db.get_bind().dialect.name
    if dialect_name == "postgresql":
        distance = cast(
            KnowledgeEmbedding.embedding.op("<=>")(
                literal(payload.query_embedding, type_=PortableVector())
            ),
            Float,
        ).label("distance")
        rows = list(db.execute(base.add_columns(distance).order_by(distance).limit(payload.limit)))
        scored = [(row[0], row[1], row[2], row[3], 1.0 - float(row[4])) for row in rows]
    else:
        rows = list(db.execute(base))
        scored = sorted(
            (
                (
                    embedding,
                    chunk,
                    document,
                    source,
                    _cosine_similarity(payload.query_embedding, embedding.embedding),
                )
                for embedding, chunk, document, source in rows
            ),
            key=lambda item: item[4],
            reverse=True,
        )[: payload.limit]

    results = [
        KnowledgeSearchResult(
            chunk_id=chunk.id,
            document_id=document.id,
            document_title=document.title,
            source_id=source.id,
            source_key=source.source_key,
            source_type=source.source_type,
            source_title=source.title,
            source_uri=source.source_uri,
            source_version=source.version,
            content=chunk.content,
            locator=chunk.locator_json,
            similarity=max(-1.0, min(1.0, similarity)),
            is_test_data=source.is_test_data or document.is_test_data or embedding.is_test_data,
        )
        for embedding, chunk, document, source, similarity in scored
    ]
    notice = (
        "Only approved chunks are returned with traceable source metadata."
        if results
        else "No approved embedding matched the requested provider, model and filters."
    )
    return KnowledgeSearchResponse(results=results, notice=notice)


def get_knowledge_status(db: Session, settings: Settings) -> KnowledgeStatusResponse:
    source_count = db.scalar(select(func.count()).select_from(KnowledgeSource)) or 0
    document_count = db.scalar(select(func.count()).select_from(KnowledgeDocument)) or 0
    pending_review_count = (
        db.scalar(
            select(func.count())
            .select_from(KnowledgeDocument)
            .where(
                KnowledgeDocument.review_status.in_(
                    ("draft", "pending", "technical_reviewed")
                )
            )
        )
        or 0
    )
    approved_chunk_count = (
        db.scalar(
            select(func.count())
            .select_from(KnowledgeChunk)
            .where(KnowledgeChunk.review_status == "approved")
        )
        or 0
    )
    embedding_count = db.scalar(select(func.count()).select_from(KnowledgeEmbedding)) or 0
    production_chunk_count = (
        db.scalar(
            select(func.count())
            .select_from(KnowledgeChunk)
            .join(KnowledgeDocument, KnowledgeChunk.document_id == KnowledgeDocument.id)
            .join(KnowledgeSource, KnowledgeDocument.source_id == KnowledgeSource.id)
            .where(
                KnowledgeChunk.review_status == "approved",
                KnowledgeDocument.review_status == "approved",
                KnowledgeSource.is_test_data.is_(False),
                KnowledgeDocument.is_test_data.is_(False),
            )
        )
        or 0
    )
    content_available = production_chunk_count > 0
    if source_count == 0:
        notice = "知识库框架已建立，但尚未导入任何经授权资料。"
    elif not content_available:
        notice = "资料已登记，但尚无通过审核的非测试知识内容。"
    else:
        notice = "知识库已有可用内容；可先全文检索，配置向量后启用混合检索。"
    return KnowledgeStatusResponse(
        content_available=content_available,
        source_count=source_count,
        document_count=document_count,
        pending_review_count=pending_review_count,
        approved_chunk_count=approved_chunk_count,
        embedding_count=embedding_count,
        embedding_provider_configured=settings.knowledge_embedding_configured,
        configured_provider=settings.knowledge_embedding_provider,
        configured_model=settings.knowledge_embedding_model,
        configured_dimensions=settings.knowledge_embedding_dimensions,
        notice=notice,
    )
