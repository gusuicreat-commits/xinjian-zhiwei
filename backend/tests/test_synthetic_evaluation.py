import os

import pytest
from sqlalchemy import create_engine

from app.evaluation.runner import (
    _evaluate_retrieval,
    _load,
    _score_retrieval_case,
    _summarize_retrieval_cases,
    _validate_disposable_postgres_target,
    _validate_retrieval_dataset,
    run_evaluation,
)


def test_synthetic_evaluation_meets_committed_thresholds() -> None:
    report = run_evaluation()

    assert report["diagnosis"]["total"] >= 30
    assert report["diagnosis"]["exact_match_rate"] == 1
    assert report["diagnosis"]["top1_cause_hit_rate"] == 1
    assert report["diagnosis"]["top3_cause_hit_rate"] == 1
    assert report["diagnosis"]["required_steps_rate"] == 1
    assert report["diagnosis"]["unsupported_high_confidence_count"] == 0
    assert report["diagnosis"]["average_response_ms"] > 0
    assert report["retrieval"]["total"] >= 50
    assert report["retrieval"]["retriever"] == (
        "app.services.hybrid_retrieval.hybrid_retrieve"
    )
    assert report["retrieval"]["recall_at_5"] >= 0.8
    assert report["retrieval"]["candidate_limits"] == {
        "lexical_top_n": 10,
        "vector_top_n": 10,
        "fused_top_k": 5,
    }
    assert report["retrieval"]["multi_relevant_query_count"] >= 5
    assert report["retrieval"]["database_dialect"] == "sqlite"
    assert 0 <= report["retrieval"]["mrr_at_5"] <= 1
    assert 0 <= report["retrieval"]["hit_rate_at_5"] <= 1
    assert report["retrieval"]["hit_rate_at_5"] != report["retrieval"]["recall_at_5"]
    assert report["retrieval"]["miss_count"] > 0
    assert report["retrieval"]["miss_count"] == len(
        report["retrieval"]["misses"]
    )
    assert all(
        {
            "expected_document_ids",
            "expected_chunk_ids",
            "actual_document_ids",
            "actual_chunk_ids",
            "missing_chunk_ids",
        }.issubset(miss)
        for miss in report["retrieval"]["misses"]
    )
    assert all(
        case["lexical_used"] and case["vector_used"]
        for case in report["retrieval"]["cases"]
    )
    assert report["retrieval"]["gate_passed"] is True
    assert report["forbidden_claims"]["patterns_checked"] >= 5
    assert report["forbidden_claims"]["hits"] == []
    assert report["episode_aggregation"]["passed"] is True
    assert report["episode_aggregation"]["episode_count"] == 1
    assert report["ai_activity"]["provider_calls"] == 0
    assert report["ai_activity"]["cache_hits"] == 0
    assert report["passed"] is True


def test_retrieval_dataset_requires_traceable_annotations() -> None:
    document = {
        "id": "document",
        "chunk_id": "chunk",
        "title": "synthetic",
        "text": "synthetic retrieval fixture",
        "is_test_data": True,
        "basis": "synthetic fixture",
    }
    query = {
        "id": "query",
        "text": "synthetic",
        "expected_document_ids": ["document"],
        "expected_chunk_ids": ["chunk"],
        "basis": "synthetic annotation",
    }
    dataset = {
        "is_test_data": True,
        "basis": "synthetic evaluation",
        "documents": [document],
        "queries": [{**query, "id": f"query-{index}"} for index in range(50)],
    }

    _validate_retrieval_dataset(dataset)

    with pytest.raises(ValueError, match="annotation basis"):
        _validate_retrieval_dataset(
            {
                **dataset,
                "queries": [
                    *dataset["queries"][:-1],
                    {**dataset["queries"][-1], "basis": ""},
                ],
            }
        )


def test_partial_recall_produces_a_non_empty_actionable_miss() -> None:
    query = {
        "id": "partial-recall",
        "text": "synthetic multi relevant query",
        "expected_document_ids": ["document-a", "document-b"],
        "expected_chunk_ids": ["chunk-a", "chunk-b"],
    }
    case = _score_retrieval_case(
        query,
        ["chunk-a", "distractor-chunk"],
        {
            "chunk-a": "document-a",
            "chunk-b": "document-b",
            "distractor-chunk": "distractor-document",
        },
        lexical_used=True,
        vector_used=True,
    )
    report = _summarize_retrieval_cases([case])

    assert report["hit_rate_at_5"] == 1
    assert report["recall_at_5"] == 0.5
    assert report["hit_rate_at_5"] != report["recall_at_5"]
    assert report["miss_count"] == 1
    assert report["misses"] == [
        {
            "id": "partial-recall",
            "text": "synthetic multi relevant query",
            "expected_document_ids": ["document-a", "document-b"],
            "expected_chunk_ids": ["chunk-a", "chunk-b"],
            "actual_document_ids": ["document-a", "distractor-document"],
            "actual_chunk_ids": ["chunk-a", "distractor-chunk"],
            "missing_chunk_ids": ["chunk-b"],
        }
    ]


def test_optional_postgres_hybrid_retrieval_acceptance() -> None:
    dsn = os.getenv("TEST_RAG_POSTGRES_DSN")
    if not dsn:
        pytest.skip("TEST_RAG_POSTGRES_DSN is not configured")

    report = _evaluate_retrieval(_load("retrieval_cases.json"), database_url=dsn)

    assert report["database_dialect"] == "postgresql"
    assert report["recall_at_5"] >= 0.8
    assert report["gate_passed"] is True


def test_postgres_evaluation_rejects_non_disposable_database_name() -> None:
    engine = create_engine("postgresql+psycopg://user:password@localhost/production")
    try:
        with pytest.raises(ValueError, match="dedicated disposable database"):
            _validate_disposable_postgres_target(engine)
    finally:
        engine.dispose()
