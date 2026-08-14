import hashlib
import json
import math
import re
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from time import perf_counter
from typing import Any

from sqlalchemy import create_engine, inspect, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.ai.clients import EmbeddingClient
from app.core.config import Settings
from app.db.base import Base
from app.diagnosis.schemas import (
    ContextLog,
    ContextReading,
    DiagnosisContext,
    ExperimentTemplateContext,
    MetricRange,
)
from app.models import (
    Device,
    DiagnosisEpisode,
    DiagnosisResult,
    KnowledgeChunk,
    KnowledgeDocument,
    KnowledgeEmbedding,
    KnowledgeSource,
)
from app.services.diagnosis import diagnose
from app.services.diagnosis_episode import upsert_episode
from app.services.hybrid_retrieval import hybrid_retrieve
from app.services.lightweight_diagnosis import build_diagnosis_core

EVALUATION_DIRECTORY = Path(__file__).resolve().parents[2] / "evaluation"


def _load(name: str) -> dict[str, Any]:
    return json.loads((EVALUATION_DIRECTORY / name).read_text(encoding="utf-8"))


def _diagnose_case(case: dict[str, Any]) -> dict[str, Any]:
    evaluated_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
    logs = []
    if case["event"] is not None:
        logs.append(
            ContextLog(
                id=f"log-{case['id']}",
                level="error",
                message="synthetic evaluation event",
                event_code=case["event"],
                occurred_at=evaluated_at,
                is_test_data=True,
            )
        )
    context = DiagnosisContext(
        device_id=f"synthetic-{case['id']}",
        evaluated_at=evaluated_at,
        last_seen_at=evaluated_at - timedelta(seconds=case["seconds_since_seen"]),
        logs=logs,
        readings=[
            ContextReading(
                id=f"reading-{case['id']}",
                sensor_type="synthetic-sensor",
                metric_key="synthetic_metric",
                value=case["value"],
                unit="synthetic-unit",
                observed_at=evaluated_at,
                is_test_data=True,
            )
        ],
        experiment_template=ExperimentTemplateContext(
            template_id="synthetic-template",
            metric_ranges={"synthetic_metric": MetricRange(minimum=0, maximum=100)},
        ),
    )
    started = perf_counter()
    outcome = diagnose(context)
    latency_ms = (perf_counter() - started) * 1000
    record = DiagnosisResult(
        id=f"diagnosis-{case['id']}",
        device_id=f"device-{case['id']}",
        evaluated_at=evaluated_at,
        ruleset_version=outcome.ruleset_version,
        ruleset_hash=outcome.ruleset_hash,
        input_fingerprint=outcome.input_fingerprint,
        matched_rules=[item.model_dump(mode="json") for item in outcome.matches],
        evidence=[
            {
                "rule_id": item.rule_id,
                "items": [evidence.model_dump(mode="json") for evidence in item.evidence],
            }
            for item in outcome.matches
        ],
        context_snapshot=context.model_dump(mode="json"),
        is_test_data=True,
    )
    core = build_diagnosis_core(record, [])
    return {
        "actual": [match.error_type for match in outcome.matches],
        "core": core,
        "latency_ms": latency_ms,
    }


def _evaluate_episode_aggregation() -> dict[str, Any]:
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    try:
        with session_factory() as db:
            device = Device(
                device_key="synthetic-evaluation-device",
                display_name="Synthetic evaluation device",
                device_type="test-fixture",
                token_hash="synthetic-hash-not-a-credential",
            )
            db.add(device)
            db.flush()
            for index in range(2):
                evaluated_at = datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(
                    seconds=index
                )
                diagnosis = DiagnosisResult(
                    device_id=device.id,
                    evaluated_at=evaluated_at,
                    ruleset_version="synthetic-evaluation",
                    ruleset_hash="0" * 64,
                    input_fingerprint=f"{index:064d}",
                    matched_rules=[
                        {
                            "rule_id": "synthetic-read-failure",
                            "error_type": "SENSOR_READ_FAILED",
                            "summary": "synthetic",
                            "evidence": [{"fact": "synthetic", "observed_value": 1}],
                        }
                    ],
                    evidence=[{"fact": "synthetic", "observed_value": 1}],
                    context_snapshot={"experiment_template": {"template_id": "synthetic"}},
                    is_test_data=True,
                )
                db.add(diagnosis)
                db.commit()
                upsert_episode(db, device, diagnosis, [], Settings(_env_file=None))
            episodes = list(db.scalars(select(DiagnosisEpisode)))
            passed = (
                len(episodes) == 1
                and episodes[0].failure_count == 2
                and episodes[0].primary_error_code == "SENSOR_READ_FAILED"
            )
            return {
                "input_diagnoses": 2,
                "episode_count": len(episodes),
                "failure_count": episodes[0].failure_count if episodes else 0,
                "passed": passed,
            }
    finally:
        Base.metadata.drop_all(engine)
        engine.dispose()


SYNTHETIC_EMBEDDING_PROVIDER = "synthetic-evaluation"
SYNTHETIC_EMBEDDING_MODEL = "deterministic-hash-v1"
SYNTHETIC_EMBEDDING_DIMENSIONS = 128
KNOWLEDGE_EVALUATION_TABLES = (
    KnowledgeSource.__table__,
    KnowledgeDocument.__table__,
    KnowledgeChunk.__table__,
    KnowledgeEmbedding.__table__,
)


def _embedding_tokens(text: str) -> set[str]:
    tokens = set(re.findall(r"[a-z0-9_]{2,}", text.lower()))
    for group in re.findall(r"[\u4e00-\u9fff]+", text):
        tokens.update(
            group[index : index + 2]
            for index in range(max(1, len(group) - 1))
        )
    return tokens


def _deterministic_test_embedding(text: str) -> list[float]:
    """Build a stable local test vector; this is not a semantic embedding model."""

    vector = [0.0] * SYNTHETIC_EMBEDDING_DIMENSIONS
    for token in _embedding_tokens(text):
        digest = hashlib.sha256(token.encode("utf-8")).digest()
        index = int.from_bytes(digest[:4], "big") % SYNTHETIC_EMBEDDING_DIMENSIONS
        vector[index] += 1.0
    norm = math.sqrt(sum(value * value for value in vector))
    if norm == 0:
        vector[0] = 1.0
        return vector
    return [value / norm for value in vector]


class _DeterministicTestEmbeddingClient(EmbeddingClient):
    provider = SYNTHETIC_EMBEDDING_PROVIDER
    model = SYNTHETIC_EMBEDDING_MODEL
    dimensions = SYNTHETIC_EMBEDDING_DIMENSIONS
    configured = True

    def embed(self, text: str) -> list[float]:
        return _deterministic_test_embedding(text)


def _validate_retrieval_dataset(retrieval: dict[str, Any]) -> None:
    documents = retrieval.get("documents")
    queries = retrieval.get("queries")
    if not retrieval.get("is_test_data") or not retrieval.get("basis"):
        raise ValueError("Retrieval evaluation must declare is_test_data and basis")
    if not isinstance(documents, list) or not documents:
        raise ValueError("Retrieval evaluation must contain documents")
    if not isinstance(queries, list) or len(queries) < 50:
        raise ValueError("Retrieval evaluation must contain at least 50 queries")

    document_ids = {item["id"] for item in documents}
    chunk_to_document = {item["chunk_id"]: item["id"] for item in documents}
    if len(document_ids) != len(documents) or len(chunk_to_document) != len(documents):
        raise ValueError("Retrieval document and chunk identifiers must be unique")
    for document in documents:
        if not document.get("is_test_data") or not document.get("basis"):
            raise ValueError(
                f"Retrieval document {document['id']} must declare test-data basis"
            )

    query_ids = {item["id"] for item in queries}
    if len(query_ids) != len(queries):
        raise ValueError("Retrieval query identifiers must be unique")
    for query in queries:
        if not query.get("basis"):
            raise ValueError(
                f"Retrieval query {query['id']} must declare annotation basis"
            )
        expected_documents = query.get("expected_document_ids")
        expected_chunks = query.get("expected_chunk_ids")
        if not expected_documents or not expected_chunks:
            raise ValueError(
                f"Retrieval query {query['id']} must name expected documents and chunks"
            )
        if len(expected_documents) != len(expected_chunks):
            raise ValueError(
                f"Retrieval query {query['id']} has mismatched expected targets"
            )
        for document_id, chunk_id in zip(expected_documents, expected_chunks):
            if document_id not in document_ids or chunk_to_document.get(chunk_id) != document_id:
                raise ValueError(
                    f"Retrieval query {query['id']} references an unknown target"
                )


@contextmanager
def _retrieval_engine(database_url: str | None = None):
    """Yield SQLite or an explicitly disposable PostgreSQL test database."""

    if database_url is None:
        engine = create_engine(
            "sqlite+pysqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        try:
            yield engine
        finally:
            engine.dispose()
        return

    engine = create_engine(database_url)
    try:
        yield engine
    finally:
        engine.dispose()


def _validate_disposable_postgres_target(engine) -> None:
    if engine.dialect.name != "postgresql":
        return
    database_name = str(engine.url.database or "")
    if not re.fullmatch(r"(?:test|tmp|rag_eval)[a-z0-9_-]*", database_name.lower()):
        raise ValueError(
            "TEST_RAG_POSTGRES_DSN must target a dedicated disposable database "
            "whose name starts with test, tmp, or rag_eval"
        )

    existing_tables = inspect(engine).get_table_names()
    if existing_tables:
        raise ValueError(
            "TEST_RAG_POSTGRES_DSN must target an empty disposable database; "
            f"found existing tables: {', '.join(sorted(existing_tables))}"
        )


def _score_retrieval_case(
    query: dict[str, Any],
    actual_chunks: list[str],
    chunk_to_document: dict[str, str],
    *,
    lexical_used: bool,
    vector_used: bool,
) -> dict[str, Any]:
    actual_documents = [chunk_to_document[item] for item in actual_chunks]
    expected_chunks = set(query["expected_chunk_ids"])
    matched_chunks = [item for item in actual_chunks if item in expected_chunks]
    missing_chunks = sorted(expected_chunks.difference(actual_chunks))
    first_rank = next(
        (
            rank
            for rank, chunk_id in enumerate(actual_chunks, 1)
            if chunk_id in expected_chunks
        ),
        None,
    )
    recall_at_5 = len(matched_chunks) / len(expected_chunks)
    return {
        "id": query["id"],
        "text": query["text"],
        "expected_document_ids": query["expected_document_ids"],
        "expected_chunk_ids": query["expected_chunk_ids"],
        "actual_document_ids": actual_documents,
        "actual_chunk_ids": actual_chunks,
        "top1_passed": bool(actual_chunks) and actual_chunks[0] in expected_chunks,
        "top3_passed": bool(expected_chunks.intersection(actual_chunks[:3])),
        "recall_at_5": recall_at_5,
        "reciprocal_rank_at_5": 1.0 / first_rank if first_rank else 0.0,
        "hit_at_5": first_rank is not None,
        "missing_chunk_ids": missing_chunks,
        "lexical_used": lexical_used,
        "vector_used": vector_used,
        "passed": recall_at_5 == 1.0,
    }


def _summarize_retrieval_cases(results: list[dict[str, Any]]) -> dict[str, Any]:
    total = len(results)
    passed = sum(item["passed"] for item in results)
    top1_passed = sum(item["top1_passed"] for item in results)
    top3_passed = sum(item["top3_passed"] for item in results)
    recall_at_5 = sum(item["recall_at_5"] for item in results) / total
    mrr_at_5 = sum(item["reciprocal_rank_at_5"] for item in results) / total
    hit_rate_at_5 = sum(item["hit_at_5"] for item in results) / total
    misses = [
        {
            "id": item["id"],
            "text": item["text"],
            "expected_document_ids": item["expected_document_ids"],
            "expected_chunk_ids": item["expected_chunk_ids"],
            "actual_document_ids": item["actual_document_ids"],
            "actual_chunk_ids": item["actual_chunk_ids"],
            "missing_chunk_ids": item["missing_chunk_ids"],
        }
        for item in results
        if not item["passed"]
    ]
    return {
        "total": total,
        "passed": passed,
        "top1_accuracy": top1_passed / total,
        "top3_accuracy": top3_passed / total,
        "recall_at_5": recall_at_5,
        "mrr_at_5": mrr_at_5,
        "hit_rate_at_5": hit_rate_at_5,
        "miss_count": len(misses),
        "misses": misses,
        "cases": results,
    }


def _evaluate_retrieval(
    retrieval: dict[str, Any], *, database_url: str | None = None
) -> dict[str, Any]:
    _validate_retrieval_dataset(retrieval)
    documents = retrieval["documents"]
    chunk_to_document = {item["chunk_id"]: item["id"] for item in documents}
    # Exercise production defaults instead of widening candidates to the entire
    # fixture corpus.  This makes a low-ranked relevant chunk a real miss.
    settings = Settings(_env_file=None)
    results: list[dict[str, Any]] = []
    with _retrieval_engine(database_url) as engine:
        _validate_disposable_postgres_target(engine)
        database_dialect = engine.dialect.name
        Base.metadata.create_all(engine, tables=KNOWLEDGE_EVALUATION_TABLES)
        session_factory = sessionmaker(bind=engine, expire_on_commit=False)
        try:
            with session_factory() as db:
                source = KnowledgeSource(
                    id="synthetic-retrieval-evaluation",
                    source_key="synthetic.retrieval.evaluation",
                    source_type="synthetic-test-fixture",
                    title="Synthetic retrieval evaluation fixture",
                    source_uri="test-fixture://evaluation/retrieval",
                    version=retrieval["dataset"],
                    license_name="test-only",
                    authorization_scope="Only for isolated synthetic evaluation",
                    metadata_json={
                        "basis": retrieval["basis"],
                        "formal_knowledge": False,
                    },
                    is_test_data=True,
                )
                db.add(source)
                for item in documents:
                    content_hash = hashlib.sha256(
                        item["text"].encode("utf-8")
                    ).hexdigest()
                    document = KnowledgeDocument(
                        id=item["id"],
                        source_id=source.id,
                        title=item["title"],
                        media_type="text/plain",
                        language="zh-CN",
                        storage_uri=(
                            f"test-fixture://evaluation/retrieval/{item['id']}"
                        ),
                        content_hash=content_hash,
                        parser_name="synthetic-evaluation",
                        parser_version="2",
                        review_status="approved",
                        is_test_data=True,
                    )
                    chunk = KnowledgeChunk(
                        id=item["chunk_id"],
                        document_id=document.id,
                        chunk_index=0,
                        content=item["text"],
                        content_hash=content_hash,
                        char_count=len(item["text"]),
                        locator_json={
                            "dataset": retrieval["dataset"],
                            "document_id": item["id"],
                        },
                        metadata_json={
                            "basis": item["basis"],
                            "is_test_data": item["is_test_data"],
                        },
                        review_status="approved",
                    )
                    embedding = KnowledgeEmbedding(
                        chunk_id=chunk.id,
                        provider=SYNTHETIC_EMBEDDING_PROVIDER,
                        model=SYNTHETIC_EMBEDDING_MODEL,
                        dimensions=SYNTHETIC_EMBEDDING_DIMENSIONS,
                        embedding=_deterministic_test_embedding(item["text"]),
                        is_test_data=True,
                    )
                    db.add_all((document, chunk, embedding))
                db.commit()

                embedding_client = _DeterministicTestEmbeddingClient()
                for query in retrieval["queries"]:
                    retrieved = hybrid_retrieve(
                        db,
                        query["text"],
                        settings,
                        embedding_client,
                        include_test_data=True,
                    )
                    actual_chunks = [item.chunk_id for item in retrieved.references[:5]]
                    results.append(
                        _score_retrieval_case(
                            query,
                            actual_chunks,
                            chunk_to_document,
                            lexical_used=retrieved.lexical_used,
                            vector_used=retrieved.vector_used,
                        )
                    )
        finally:
            Base.metadata.drop_all(engine, tables=KNOWLEDGE_EVALUATION_TABLES)

    summary = _summarize_retrieval_cases(results)
    threshold = 0.8
    return {
        "dataset": retrieval["dataset"],
        "is_test_data": True,
        "basis": retrieval["basis"],
        "retriever": "app.services.hybrid_retrieval.hybrid_retrieve",
        "embedding_fixture": SYNTHETIC_EMBEDDING_MODEL,
        "database_dialect": database_dialect,
        "candidate_limits": {
            "lexical_top_n": settings.rag_lexical_top_n,
            "vector_top_n": settings.rag_vector_top_n,
            "fused_top_k": settings.rag_fused_top_k,
        },
        "multi_relevant_query_count": sum(
            len(item["expected_chunk_ids"]) > 1 for item in retrieval["queries"]
        ),
        **summary,
        "threshold": threshold,
        "gate_passed": summary["recall_at_5"] >= threshold,
    }


def run_evaluation() -> dict[str, Any]:
    diagnosis = _load("golden_cases.json")
    retrieval = _load("retrieval_cases.json")
    forbidden = _load("forbidden_claims.json")

    diagnosis_results = []
    latencies = []
    top1_cause_hits = 0
    top3_cause_hits = 0
    cause_cases = 0
    step_cases = 0
    step_passed = 0
    unsupported_high_confidence = 0
    for case in diagnosis["cases"]:
        evaluated = _diagnose_case(case)
        actual = evaluated["actual"]
        core = evaluated["core"]
        latencies.append(evaluated["latency_ms"])
        if core.confidence >= 0.7 and not core.evidence:
            unsupported_high_confidence += 1
        primary = case["expected"][0] if case["expected"] else None
        if primary:
            cause_cases += 1
            expected_cause = diagnosis["expected_causes_by_error"][primary]
            if core.possible_causes and core.possible_causes[0] == expected_cause:
                top1_cause_hits += 1
            if expected_cause in core.possible_causes[:3]:
                top3_cause_hits += 1
            step_cases += 1
            rendered_steps = " ".join(core.suggested_steps)
            required_fragments = diagnosis["required_step_fragments_by_error"][primary]
            if all(fragment in rendered_steps for fragment in required_fragments):
                step_passed += 1
        diagnosis_results.append(
            {
                "id": case["id"],
                "expected": case["expected"],
                "actual": actual,
                "passed": actual == case["expected"],
            }
        )

    retrieval_report = _evaluate_retrieval(retrieval)

    generated_text = " ".join(
        match
        for result in diagnosis_results
        for match in result["actual"]
    )
    forbidden_hits = [
        pattern for pattern in forbidden["patterns"] if pattern in generated_text
    ]
    diagnosis_passed = sum(item["passed"] for item in diagnosis_results)
    episode = _evaluate_episode_aggregation()
    average_latency_ms = sum(latencies) / len(latencies)
    cause_top1_rate = top1_cause_hits / cause_cases
    cause_top3_rate = top3_cause_hits / cause_cases
    required_steps_rate = step_passed / step_cases
    return {
        "evaluation_version": "3",
        "is_test_data": True,
        "claim_boundary": (
            "合成评测只验证当前示例规则和生产同源混合检索代码，"
            "不代表真实诊断能力、正式知识质量或真实 Embedding 质量"
        ),
        "diagnosis": {
            "total": len(diagnosis_results),
            "passed": diagnosis_passed,
            "exact_match_rate": diagnosis_passed / len(diagnosis_results),
            "top1_cause_hit_rate": cause_top1_rate,
            "top3_cause_hit_rate": cause_top3_rate,
            "required_steps_rate": required_steps_rate,
            "unsupported_high_confidence_count": unsupported_high_confidence,
            "average_response_ms": average_latency_ms,
            "threshold": 1.0,
            "cases": diagnosis_results,
        },
        "retrieval": retrieval_report,
        "forbidden_claims": {
            "patterns_checked": len(forbidden["patterns"]),
            "hits": forbidden_hits,
            "passed": not forbidden_hits,
        },
        "episode_aggregation": episode,
        "ai_activity": {
            "provider_calls": 0,
            "cache_hits": 0,
            "passed": True,
            "reason": "合成评测只执行确定性规则、解释、检索与 Episode，不调用 AI",
        },
        "passed": (
            diagnosis_passed == len(diagnosis_results)
            and cause_top1_rate == 1.0
            and cause_top3_rate == 1.0
            and required_steps_rate == 1.0
            and unsupported_high_confidence == 0
            and retrieval_report["gate_passed"]
            and not forbidden_hits
            and episode["passed"]
        ),
    }
