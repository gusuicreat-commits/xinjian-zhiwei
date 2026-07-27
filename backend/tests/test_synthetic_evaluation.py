from app.evaluation.runner import run_evaluation


def test_synthetic_evaluation_meets_committed_thresholds() -> None:
    report = run_evaluation()

    assert report["diagnosis"]["total"] >= 30
    assert report["diagnosis"]["exact_match_rate"] == 1
    assert report["diagnosis"]["top1_cause_hit_rate"] == 1
    assert report["diagnosis"]["top3_cause_hit_rate"] == 1
    assert report["diagnosis"]["required_steps_rate"] == 1
    assert report["diagnosis"]["unsupported_high_confidence_count"] == 0
    assert report["diagnosis"]["average_response_ms"] > 0
    assert report["retrieval"]["total"] >= 10
    assert report["retrieval"]["top1_accuracy"] >= 0.9
    assert report["retrieval"]["top3_accuracy"] == 1
    assert report["forbidden_claims"]["patterns_checked"] >= 5
    assert report["forbidden_claims"]["hits"] == []
    assert report["episode_aggregation"]["passed"] is True
    assert report["episode_aggregation"]["episode_count"] == 1
    assert report["ai_activity"]["provider_calls"] == 0
    assert report["ai_activity"]["cache_hits"] == 0
    assert report["passed"] is True
