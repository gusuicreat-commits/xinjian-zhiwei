from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app.diagnosis.loader import load_rules
from app.diagnosis.matcher import evaluate_rules
from app.diagnosis.schemas import (
    ContextLog,
    ContextReading,
    DiagnosisContext,
    ExperimentTemplateContext,
    MetricRange,
)

NOW = datetime(2026, 7, 20, 8, 0, tzinfo=timezone.utc)


def context(**overrides: object) -> DiagnosisContext:
    payload = {
        "device_id": "generic-test-device",
        "evaluated_at": NOW,
        "last_seen_at": NOW,
        "logs": [],
        "heartbeats": [],
        "readings": [],
        "experiment_template": None,
    }
    payload.update(overrides)
    return DiagnosisContext.model_validate(payload)


def evaluate(value: DiagnosisContext):
    ruleset, ruleset_hash = load_rules()
    return evaluate_rules(value, ruleset, ruleset_hash)


def test_normal_context_has_no_matches() -> None:
    assert evaluate(context()).matches == []


def test_sensor_read_failure_has_traceable_log_evidence() -> None:
    log = ContextLog(
        id="log-1",
        level="error",
        message="generic sensor read failed",
        event_code="SENSOR_READ_FAILED",
        occurred_at=NOW,
        is_test_data=True,
    )
    match = evaluate(context(logs=[log])).matches[0]

    assert match.error_type == "SENSOR_READ_FAILED"
    assert match.evidence[0].details[0]["log_id"] == "log-1"


def test_offline_device_has_elapsed_time_evidence() -> None:
    outcome = evaluate(context(last_seen_at=NOW - timedelta(seconds=91)))

    assert [match.error_type for match in outcome.matches] == ["DEVICE_OFFLINE"]
    assert outcome.matches[0].evidence[0].observed_value == 91


def test_out_of_range_reading_uses_generic_template_bounds() -> None:
    reading = ContextReading(
        id="reading-1",
        sensor_type="generic",
        metric_key="metric_a",
        value=10.1,
        unit=None,
        observed_at=NOW,
        is_test_data=True,
    )
    template = ExperimentTemplateContext(
        template_id="template-placeholder",
        metric_ranges={"metric_a": MetricRange(minimum=0, maximum=10)},
    )
    match = evaluate(context(readings=[reading], experiment_template=template)).matches[0]

    assert match.error_type == "VALUE_OUT_OF_RANGE"
    assert match.evidence[0].details[0]["maximum"] == 10


def test_same_context_and_rules_are_deterministic() -> None:
    value = context(last_seen_at=NOW - timedelta(seconds=91))

    assert evaluate(value) == evaluate(value)


def test_yaml_change_updates_behavior_without_program_change(tmp_path: Path) -> None:
    rules = """
version: custom-test
rules:
  - id: configurable-offline
    error_type: DEVICE_OFFLINE
    priority: 1
    summary: configurable threshold
    conditions:
      - fact: seconds_since_last_seen
        operator: gte
        value: 10
"""
    (tmp_path / "custom.yaml").write_text(rules, encoding="utf-8")
    ruleset, ruleset_hash = load_rules(tmp_path)

    outcome = evaluate_rules(
        context(last_seen_at=NOW - timedelta(seconds=11)), ruleset, ruleset_hash
    )
    assert [match.rule_id for match in outcome.matches] == ["configurable-offline"]


def test_loader_rejects_duplicate_rule_ids(tmp_path: Path) -> None:
    (tmp_path / "duplicate.yaml").write_text(
        """
version: test
rules:
  - &rule
    id: duplicate
    error_type: TEST
    summary: first
    conditions: [{fact: log_event_count, operator: gte, value: 1}]
  - <<: *rule
    summary: second
""",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="unique"):
        load_rules(tmp_path)
