from datetime import datetime, timezone

from app.diagnosis.fault_tree import evaluate_fault_tree
from app.diagnosis.fault_tree_loader import load_fault_trees
from app.diagnosis.schemas import (
    ContextLog,
    DiagnosisContext,
    DiagnosisMatch,
    DiagnosisOutcome,
    EvidenceItem,
)

NOW = datetime(2026, 7, 20, 8, 0, tzinfo=timezone.utc)


def diagnosis(error_type: str = "SENSOR_READ_FAILED") -> DiagnosisOutcome:
    return DiagnosisOutcome(
        ruleset_version="test",
        ruleset_hash="a" * 64,
        input_fingerprint="b" * 64,
        matches=[
            DiagnosisMatch(
                rule_id="test-rule",
                error_type=error_type,
                priority=1,
                summary="test anomaly",
                evidence=[EvidenceItem(fact="test", observed_value=1)],
            )
        ],
    )


def context(*event_codes: str) -> DiagnosisContext:
    return DiagnosisContext(
        device_id="generic-test-device",
        evaluated_at=NOW,
        last_seen_at=NOW,
        logs=[
            ContextLog(
                id=f"log-{index}",
                level="error",
                message="explicit fault-tree test evidence",
                event_code=event_code,
                occurred_at=NOW,
                is_test_data=True,
            )
            for index, event_code in enumerate(event_codes)
        ],
    )


def tree(tree_id: str):
    tree_set, _ = load_fault_trees()
    return next(item for item in tree_set.trees if item.id == tree_id)


def test_loader_provides_three_placeholder_trees() -> None:
    tree_set, digest = load_fault_trees()

    assert len(tree_set.trees) == 3
    assert all(item.status == "placeholder" for item in tree_set.trees)
    assert len(digest) == 64


def test_root_anomaly_returns_multiple_low_confidence_causes() -> None:
    result = evaluate_fault_tree(
        tree("sensor-read-failure-example-v1"),
        context(),
        diagnosis(),
        failure_count=1,
        anomaly_duration_seconds=0,
    )

    assert result is not None
    assert len(result.ranked_causes) == 3
    assert {item.confidence for item in result.ranked_causes} == {"low"}
    assert {item.score for item in result.ranked_causes} == {20}


def test_specific_evidence_ranks_supported_cause_first() -> None:
    result = evaluate_fault_tree(
        tree("sensor-read-failure-example-v1"),
        context("SENSOR_SIGNAL_TIMEOUT"),
        diagnosis(),
        failure_count=1,
        anomaly_duration_seconds=0,
    )

    assert result is not None
    assert result.ranked_causes[0].cause_id == "sensor-signal-path"
    assert result.ranked_causes[0].score == 75
    assert result.ranked_causes[0].confidence == "high"
    assert all(item.score < 70 for item in result.ranked_causes[1:])


def test_untriggered_tree_produces_no_guidance() -> None:
    result = evaluate_fault_tree(
        tree("led-no-light-example-v1"),
        context(),
        DiagnosisOutcome(
            ruleset_version="test",
            ruleset_hash="a" * 64,
            input_fingerprint="b" * 64,
            matches=[],
        ),
        failure_count=1,
        anomaly_duration_seconds=0,
    )

    assert result is None


def test_led_and_button_templates_return_ranked_causes() -> None:
    empty_diagnosis = DiagnosisOutcome(
        ruleset_version="test",
        ruleset_hash="a" * 64,
        input_fingerprint="b" * 64,
        matches=[],
    )
    for tree_id, event_code in (
        ("led-no-light-example-v1", "LED_NO_RESPONSE"),
        ("button-no-response-example-v1", "BUTTON_NO_RESPONSE"),
    ):
        result = evaluate_fault_tree(
            tree(tree_id),
            context(event_code),
            empty_diagnosis,
            failure_count=1,
            anomaly_duration_seconds=0,
        )
        assert result is not None
        assert len(result.ranked_causes) == 3


def test_hint_level_escalates_by_count_or_duration() -> None:
    selected_tree = tree("sensor-read-failure-example-v1")
    by_count = evaluate_fault_tree(
        selected_tree,
        context(),
        diagnosis(),
        failure_count=10,
        anomaly_duration_seconds=0,
    )
    by_duration = evaluate_fault_tree(
        selected_tree,
        context(),
        diagnosis(),
        failure_count=1,
        anomaly_duration_seconds=1800,
    )

    assert by_count is not None and by_count.hint_level == 4
    assert by_duration is not None and by_duration.hint_level == 4
    assert by_count.teacher_intervention_required is True
