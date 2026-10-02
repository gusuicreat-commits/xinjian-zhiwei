import hashlib
from dataclasses import dataclass
from typing import Any, Optional

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload, selectinload

from app.core.config import Settings
from app.models.knowledge import (
    KnowledgeCase,
    KnowledgeChunk,
    KnowledgeDocument,
    KnowledgeReview,
    KnowledgeSource,
)
from app.models.knowledge_access import KnowledgeSourceGrant
from app.schemas.knowledge import (
    KnowledgeChunkResponse,
    KnowledgeChunkWorkspaceItem,
    KnowledgeDocumentResponse,
    KnowledgeReviewRequest,
    KnowledgeReviewResponse,
    KnowledgeSourceCreate,
    KnowledgeSourceResponse,
    KnowledgeStatusResponse,
    KnowledgeTextImportRequest,
    KnowledgeWorkspaceResponse,
)
from app.services.auth import ActorContext, AuthorizationDenied
from app.services.knowledge_access import (
    audit_workspace,
    document_scope,
    source_scope,
    visible_sources,
    workspace_actor,
)
from app.services.provenance import derive_test_flag

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
    ("pending", "approved"): "formal_approver",
    ("pending", "rejected"): "formal_approver",
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


def create_source(
    db: Session, payload: KnowledgeSourceCreate, *, actor_context=None
) -> KnowledgeSourceResponse:
    workspace_actor(db, actor_context, "organize")
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
        db.flush()
        db.add(
            KnowledgeSourceGrant(
                source_id=source.id, user_id=actor_context.user_id, capability="organize"
            )
        )
        audit_workspace(
            db,
            actor_context,
            "source_created",
            "knowledge_source",
            source.id,
            is_test_data=source.is_test_data,
        )
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise KnowledgeServiceError(
            409, "KNOWLEDGE_SOURCE_EXISTS", "Knowledge source key already exists"
        ) from exc
    db.refresh(source)
    return _source_response(source)


def list_sources(
    db: Session, *, actor_context=None, after_id="", limit=100
) -> list[KnowledgeSourceResponse]:
    allowed = visible_sources(db, actor_context)
    sources = db.scalars(
        select(KnowledgeSource)
        .where(KnowledgeSource.id.in_(allowed), KnowledgeSource.id > after_id)
        .order_by(KnowledgeSource.id)
        .limit(min(max(limit, 1), 100))
    ).all()
    return [_source_response(source) for source in sources]


def import_text_document(
    db: Session,
    source_id: str,
    payload: KnowledgeTextImportRequest,
    settings: Settings,
    *,
    actor_context=None,
) -> KnowledgeDocumentResponse:
    source = source_scope(db, actor_context, source_id)
    payload = payload.model_copy(update={"organizer_ref": actor_context.user_id})
    if source is None:
        raise KnowledgeServiceError(404, "KNOWLEDGE_SOURCE_NOT_FOUND", "Knowledge source not found")
    if payload.media_type not in {
        "text/plain",
        "text/markdown",
        "text/csv",
        "application/pdf",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    }:
        raise KnowledgeServiceError(
            422,
            "UNSUPPORTED_KNOWLEDGE_MEDIA_TYPE",
            "Knowledge media type is not supported",
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
    document_is_test = derive_test_flag(source.is_test_data, explicit=payload.is_test_data)
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
    audit_workspace(
        db,
        actor_context,
        "document_import",
        "knowledge_document",
        document.id,
        is_test_data=document.is_test_data,
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


def get_document_workspace(
    db: Session, document_id: str, *, actor_context=None
) -> KnowledgeWorkspaceResponse:
    document_scope(db, actor_context, document_id, "view")
    document = db.scalar(
        select(KnowledgeDocument)
        .where(KnowledgeDocument.id == document_id)
        .options(selectinload(KnowledgeDocument.chunks))
    )
    if document is None:
        raise KnowledgeServiceError(
            404,
            "KNOWLEDGE_DOCUMENT_NOT_FOUND",
            "Knowledge document not found",
        )
    return KnowledgeWorkspaceResponse(
        document_id=document.id,
        title=document.title,
        review_status=document.review_status,
        chunks=[
            KnowledgeChunkWorkspaceItem(
                id=chunk.id,
                chunk_index=chunk.chunk_index,
                content=chunk.content,
                content_hash=chunk.content_hash,
                char_count=chunk.char_count,
                locator=chunk.locator_json,
                metadata=chunk.metadata_json,
                review_status=chunk.review_status,
            )
            for chunk in sorted(document.chunks, key=lambda item: item.chunk_index)
        ],
    )


def _editable_chunk(db: Session, chunk_id: str, actor_context) -> KnowledgeChunk:
    if actor_context is None:
        raise AuthorizationDenied(401)
    document_id = db.scalar(select(KnowledgeChunk.document_id).where(KnowledgeChunk.id == chunk_id))
    document_scope(db, actor_context, document_id)
    chunk = db.scalar(
        select(KnowledgeChunk)
        .where(KnowledgeChunk.id == chunk_id)
        .execution_options(populate_existing=True)
        .options(joinedload(KnowledgeChunk.document))
    )
    if chunk is None:
        raise KnowledgeServiceError(404, "KNOWLEDGE_CHUNK_NOT_FOUND", "Knowledge chunk not found")
    if chunk.document.review_status != "draft":
        raise KnowledgeServiceError(
            409,
            "KNOWLEDGE_CHUNK_IMMUTABLE",
            "Only draft document chunks can be edited",
        )
    return chunk


def update_chunk(
    db: Session,
    chunk_id: str,
    *,
    content: Optional[str],
    metadata: Optional[dict[str, Any]],
    actor_context=None,
) -> KnowledgeWorkspaceResponse:
    chunk = _editable_chunk(db, chunk_id, actor_context)
    if content is not None:
        normalized = _normalize_text(content)
        if not normalized:
            raise KnowledgeServiceError(422, "EMPTY_KNOWLEDGE_CHUNK", "Chunk cannot be empty")
        chunk.content = normalized
        chunk.content_hash = _hash_text(normalized)
        chunk.char_count = len(normalized)
    if metadata is not None:
        chunk.metadata_json = {**metadata, "organizer_ref": actor_context.user_id}
    document_id = chunk.document_id
    audit_workspace(db, actor_context, "chunk_update", "knowledge_chunk", chunk.id)
    db.commit()
    return get_document_workspace(db, document_id, actor_context=actor_context)


def _reindex_chunks(db: Session, chunks: list[KnowledgeChunk]) -> None:
    for index, chunk in enumerate(chunks):
        chunk.chunk_index = -(index + 1)
    db.flush()
    for index, chunk in enumerate(chunks):
        chunk.chunk_index = index


def split_chunk_at(
    db: Session,
    chunk_id: str,
    offset: int,
    *,
    actor_context=None,
) -> KnowledgeWorkspaceResponse:
    chunk = _editable_chunk(db, chunk_id, actor_context)
    if offset >= len(chunk.content):
        raise KnowledgeServiceError(422, "INVALID_CHUNK_SPLIT", "Split offset is outside content")
    left = chunk.content[:offset].strip()
    right = chunk.content[offset:].strip()
    if not left or not right:
        raise KnowledgeServiceError(422, "INVALID_CHUNK_SPLIT", "Split creates an empty chunk")
    document = chunk.document
    chunks = sorted(document.chunks, key=lambda item: item.chunk_index)
    chunk.content = left
    chunk.content_hash = _hash_text(left)
    chunk.char_count = len(left)
    new_chunk = KnowledgeChunk(
        document=document,
        chunk_index=-999999,
        content=right,
        content_hash=_hash_text(right),
        char_count=len(right),
        locator_json={**chunk.locator_json, "manually_split": True},
        metadata_json=dict(chunk.metadata_json),
        review_status="draft",
    )
    position = chunks.index(chunk) + 1
    chunks.insert(position, new_chunk)
    db.add(new_chunk)
    _reindex_chunks(db, chunks)
    audit_workspace(db, actor_context, "chunks_changed", "knowledge_document", document.id)
    db.commit()
    return get_document_workspace(db, document.id, actor_context=actor_context)


def merge_chunks(
    db: Session,
    chunk_ids: list[str],
    *,
    actor_context=None,
) -> KnowledgeWorkspaceResponse:
    if not chunk_ids:
        raise KnowledgeServiceError(422, "EMPTY_CHUNKS", "Select chunks to merge")
    documents = list(
        db.scalars(select(KnowledgeChunk.document_id).where(KnowledgeChunk.id.in_(chunk_ids)))
    )
    # A merge is one document operation. Reject mixed/missing targets uniformly
    # before acquiring any actor lock, avoiding source -> actor -> source cycles.
    if len(documents) != len(set(chunk_ids)) or len(set(documents)) != 1:
        raise KnowledgeServiceError(404, "KNOWLEDGE_CHUNK_NOT_FOUND", "A chunk was not found")
    document_scope(db, actor_context, documents[0])
    chunks = list(
        db.scalars(
            select(KnowledgeChunk)
            .where(KnowledgeChunk.id.in_(chunk_ids))
            .options(joinedload(KnowledgeChunk.document))
        )
    )
    if len(chunks) != len(set(chunk_ids)):
        raise KnowledgeServiceError(404, "KNOWLEDGE_CHUNK_NOT_FOUND", "A chunk was not found")
    chunks.sort(key=lambda item: item.chunk_index)
    if len({item.document_id for item in chunks}) != 1:
        raise KnowledgeServiceError(422, "CHUNK_DOCUMENT_MISMATCH", "Chunks must share a document")
    if any(item.document.review_status != "draft" for item in chunks):
        raise KnowledgeServiceError(409, "KNOWLEDGE_CHUNK_IMMUTABLE", "Document is not draft")
    indexes = [item.chunk_index for item in chunks]
    if indexes != list(range(indexes[0], indexes[0] + len(indexes))):
        raise KnowledgeServiceError(422, "CHUNKS_NOT_CONSECUTIVE", "Chunks must be consecutive")
    document = chunks[0].document
    keeper = chunks[0]
    merged = "\n".join(item.content for item in chunks)
    keeper.content = merged
    keeper.content_hash = _hash_text(merged)
    keeper.char_count = len(merged)
    all_chunks = sorted(document.chunks, key=lambda item: item.chunk_index)
    for item in chunks[1:]:
        all_chunks.remove(item)
        document.chunks.remove(item)
        db.delete(item)
    db.flush()
    _reindex_chunks(db, all_chunks)
    audit_workspace(db, actor_context, "chunks_merged", "knowledge_document", document.id)
    db.commit()
    return get_document_workspace(db, document.id, actor_context=actor_context)


def delete_chunk(db: Session, chunk_id: str, *, actor_context=None) -> KnowledgeWorkspaceResponse:
    chunk = _editable_chunk(db, chunk_id, actor_context)
    document = chunk.document
    chunks = sorted(document.chunks, key=lambda item: item.chunk_index)
    if len(chunks) == 1:
        raise KnowledgeServiceError(
            409,
            "LAST_CHUNK_DELETE_FORBIDDEN",
            "A document must retain at least one chunk",
        )
    chunks.remove(chunk)
    document.chunks.remove(chunk)
    db.delete(chunk)
    db.flush()
    _reindex_chunks(db, chunks)
    audit_workspace(db, actor_context, "chunks_changed", "knowledge_document", document.id)
    db.commit()
    return get_document_workspace(db, document.id, actor_context=actor_context)


def review_document(
    db: Session,
    document_id: str,
    payload: KnowledgeReviewRequest,
    *,
    actor_context: ActorContext | None = None,
) -> KnowledgeReviewResponse:
    capability = "review" if payload.reviewer_role == "formal_approver" else "organize"
    document_scope(db, actor_context, document_id, capability)
    actor = workspace_actor(db, actor_context, capability)
    payload = payload.model_copy(update={"reviewer_ref": actor.id})
    document = db.scalar(
        select(KnowledgeDocument)
        .where(KnowledgeDocument.id == document_id)
        .execution_options(populate_existing=True)
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
    required_role = REVIEW_TRANSITIONS.get((document.review_status, payload.decision))
    if (
        document.review_status == "pending"
        and payload.decision == "draft"
        and document.submitted_by_user_id is None
    ):
        required_role = "organizer"  # legacy unverified submission must be explicitly resubmitted
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
    organizer_ref = document.submitted_by_user_id
    if payload.reviewer_role == "formal_approver" and organizer_ref is None:
        raise KnowledgeServiceError(
            409,
            "KNOWLEDGE_SUBMITTER_UNVERIFIED",
            "A current organizer must submit this document first",
        )
    if (
        payload.reviewer_role == "formal_approver"
        and organizer_ref
        and payload.reviewer_ref == organizer_ref
    ):
        raise KnowledgeServiceError(
            409,
            "KNOWLEDGE_SELF_REVIEW_FORBIDDEN",
            "The organizer cannot perform formal approval",
        )
    if payload.decision == "approved" and not document.source.authorization_scope:
        raise KnowledgeServiceError(
            409,
            "KNOWLEDGE_AUTHORIZATION_REQUIRED",
            "Authorization scope must be recorded before approval",
        )
    if payload.reviewer_role == "organizer" and payload.decision == "pending":
        document.submitted_by_user_id = actor.id
        for chunk in document.chunks:
            chunk.metadata_json = {
                **chunk.metadata_json,
                "organizer_ref": payload.reviewer_ref,
            }
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


def get_global_knowledge_status(
    db: Session, settings: Settings, *, actor_context=None
) -> KnowledgeStatusResponse:
    # Case availability belongs to the diagnosis contract; workspace totals must
    # use the same explicit source grants as workspace APIs.
    from app.services.auth import authorize_actor, user_access
    from app.services.knowledge_access import CAPABILITIES

    workspace_counts = None
    if isinstance(actor_context, ActorContext):
        authorize_actor(db, actor_context, "dashboard.read")
        roles, permissions = user_access(db, actor_context.user_id)
        if any(
            role in roles and permission in permissions
            for permission, role in CAPABILITIES.values()
        ):
            workspace_counts = get_knowledge_status(db, settings, actor_context=actor_context)
    source_count = workspace_counts.source_count if workspace_counts else 0
    document_count = workspace_counts.document_count if workspace_counts else 0
    approved_chunk_count = workspace_counts.approved_chunk_count if workspace_counts else 0
    pending_review_count = workspace_counts.pending_review_count if workspace_counts else 0
    case_count = db.scalar(select(func.count()).select_from(KnowledgeCase)) or 0
    approved_case_count = (
        db.scalar(
            select(func.count())
            .select_from(KnowledgeCase)
            .where(
                KnowledgeCase.review_status == "approved",
                KnowledgeCase.is_test_data.is_(False),
            )
        )
        or 0
    )
    content_available = approved_case_count > 0
    if case_count == 0:
        notice = "结构化知识库已建立，但尚未同步知识案例。"
    elif not content_available:
        notice = "案例已同步，但尚无通过审核的非测试结构化案例。"
    else:
        notice = "已启用基于实验类型、错误类型和证据的结构化案例匹配。"
    notice += (
        " 工作区统计仅包含当前授权资料。"
        if workspace_counts
        else " 工作区资料访问受限，未显示其统计。"
    )
    return KnowledgeStatusResponse(
        content_available=content_available,
        source_count=source_count,
        document_count=document_count,
        pending_review_count=pending_review_count,
        approved_chunk_count=approved_chunk_count,
        case_count=case_count,
        approved_case_count=approved_case_count,
        notice=notice,
    )


def get_knowledge_status(
    db: Session, settings: Settings, *, actor_context=None
) -> KnowledgeStatusResponse:
    allowed = visible_sources(db, actor_context)
    docs = select(KnowledgeDocument.id).where(KnowledgeDocument.source_id.in_(allowed))
    source_count = (
        db.scalar(
            select(func.count()).select_from(KnowledgeSource).where(KnowledgeSource.id.in_(allowed))
        )
        or 0
    )
    document_count = (
        db.scalar(
            select(func.count())
            .select_from(KnowledgeDocument)
            .where(KnowledgeDocument.id.in_(docs))
        )
        or 0
    )
    approved = (
        db.scalar(
            select(func.count())
            .select_from(KnowledgeChunk)
            .where(KnowledgeChunk.document_id.in_(docs), KnowledgeChunk.review_status == "approved")
        )
        or 0
    )
    pending = (
        db.scalar(
            select(func.count())
            .select_from(KnowledgeDocument)
            .where(
                KnowledgeDocument.id.in_(docs),
                KnowledgeDocument.review_status.in_(["draft", "pending"]),
            )
        )
        or 0
    )
    return KnowledgeStatusResponse(
        source_count=source_count,
        document_count=document_count,
        approved_chunk_count=approved,
        pending_review_count=pending,
        case_count=0,
        approved_case_count=0,
        content_available=False,
        notice="仅统计当前授权资料；尚未评估诊断案例的可用性。",
    )
