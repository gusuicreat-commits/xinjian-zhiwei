"""Synthetic persisted facts exercise candidate linkage, not hardware causality."""

import copy
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest
from sqlalchemy import select

from app.ai.diagnosis_graph import _candidate_evidence_refs
from app.ai.reasoning import _fallback_reasoning, _validate_reasoning
from app.diagnosis.fault_tree import evaluate_fault_tree
from app.diagnosis.matcher import evaluate_rules
from app.diagnosis.schemas import (
    ContextEvent,
    ContextObservation,
    DiagnosisContext,
    DiagnosisMatch,
    EvidenceItem,
)
from app.experiment_packages.loader import load_experiment_package
from app.knowledge.validation import validate_reasoning_against_knowledge
from app.models import Device, DiagnosisEvidence
from app.services.diagnosis import save_diagnosis_result


@pytest.fixture
def persisted_facts(api_context):
    now = datetime.now(timezone.utc)
    bundle, _ = load_experiment_package(
        Path(__file__).resolve().parents[1] / "experiment_packages/dht11_temperature_humidity"
    )
    with api_context["session_factory"]() as db:
        device = db.scalar(select(Device))
        context = DiagnosisContext(
            device_id=device.id,
            evaluated_at=now,
            last_seen_at=now,
            experiment_package_is_test_data=True,
            events=[
                ContextEvent(
                    id="heartbeat:heartbeat-source",
                    type="device.heartbeat",
                    source="device_heartbeat",
                    source_ref="heartbeat-source",
                    occurred_at=now,
                    status="normal",
                ),
                *[
                    ContextEvent(
                        id=f"event:failure-{index}:dht",
                        type="sensor.read_failed",
                        component_id="dht11",
                        source="device_log",
                        source_ref=f"failure-{index}",
                        occurred_at=now,
                        status="error",
                    )
                    for index in range(5)
                ],
                ContextEvent(
                    id="event:other-source:other",
                    type="synthetic.other_failure",
                    source="device_log",
                    source_ref="other-source",
                    occurred_at=now,
                    status="error",
                ),
            ],
            observations=[
                ContextObservation(
                    id=f"reading:{source}",
                    source="sensor_reading",
                    source_ref=source,
                    metric=metric,
                    value=value,
                    status="normal",
                    observed_at=now,
                )
                for source, metric, value in (
                    ("command-source", "gpio_command_level", 1),
                    ("actual-source", "gpio_actual_level", 0),
                )
            ],
        )
        outcome = evaluate_rules(context, bundle.rules, "synthetic-ruleset-hash")
        outcome.matches.append(
            DiagnosisMatch(
                rule_id="other-rule",
                error_type="SYNTHETIC_OTHER_ERROR",
                priority=1,
                summary="Unrelated synthetic anomaly.",
                evidence=[
                    EvidenceItem(
                        fact="event_type_count",
                        observed_value=1,
                        details=[{"event_id": "event:other-source:other"}],
                    )
                ],
            )
        )
        diagnosis = save_diagnosis_result(db, device, context, outcome)
        rows = list(
            db.scalars(
                select(DiagnosisEvidence).where(DiagnosisEvidence.diagnosis_id == diagnosis.id)
            )
        )
        tree = evaluate_fault_tree(
            bundle.fault_trees.trees[0],
            context,
            outcome,
            failure_count=1,
            anomaly_duration_seconds=0,
        )
        yield db, device, context, outcome, diagnosis, rows, tree


def test_real_dht_rule_hit_links_aggregate_and_all_matching_events(persisted_facts):
    _, _, _, _, diagnosis, rows, tree = persisted_facts
    expected = {
        row.id
        for row in rows
        if row.evidence_type in {"sensor.read_failed", "rule.failure_count_in_window"}
    }
    assert len(expected) == 6  # Five original failures and their aggregate rule fact.
    assert len(tree.ranked_causes) == 3
    for cause in tree.ranked_causes:
        refs = _candidate_evidence_refs(cause.model_dump(), diagnosis, rows)
        assert set(refs) == expected
        assert len(refs) == len(set(refs))


def test_same_source_in_other_diagnosis_cannot_replace_current_evidence(persisted_facts):
    db, device, context, outcome, diagnosis, rows, tree = persisted_facts
    other = save_diagnosis_result(db, device, context, outcome)
    foreign_rows = list(
        db.scalars(select(DiagnosisEvidence).where(DiagnosisEvidence.diagnosis_id == other.id))
    )
    cause = tree.ranked_causes[0].model_dump()
    expected = _candidate_evidence_refs(cause, diagnosis, rows)
    assert _candidate_evidence_refs(cause, diagnosis, [*foreign_rows, *rows]) == expected
    assert not set(expected) & {row.id for row in foreign_rows}


def test_direct_log_criterion_resolves_its_log_not_first_failure(persisted_facts):
    _, _, _, _, diagnosis, rows, _ = persisted_facts
    cause = {"evidence": [{"fact": "log_event_count", "details": [{"log_id": "failure-3"}]}]}
    expected = next(row.id for row in rows if row.source_ref == "failure-3")
    assert _candidate_evidence_refs(cause, diagnosis, rows) == [expected]


def test_led_behavior_references_preserve_command_and_actual_observation(persisted_facts):
    _, _, _, _, diagnosis, rows, _ = persisted_facts
    cause = {
        "evidence": [
            {
                "fact": "expected_behavior_violation_count",
                "details": [
                    {
                        "evidence_refs": [
                            "sensor_reading:command-source",
                            "sensor_reading:actual-source",
                        ]
                    }
                ],
            }
        ]
    }
    refs = _candidate_evidence_refs(cause, diagnosis, rows)
    assert {row.evidence_type for row in rows if row.id in refs} == {
        "observation.gpio_command_level",
        "observation.gpio_actual_level",
    }
    assert len(refs) == 2


@pytest.mark.parametrize("missing", ["rule_id", "error_type", "all_related_rows"])
def test_missing_linkage_does_not_borrow_heartbeat_or_other_anomaly(persisted_facts, missing):
    _, _, _, _, diagnosis, rows, tree = persisted_facts
    cause = copy.deepcopy(tree.ranked_causes[0].model_dump())
    if missing == "all_related_rows":
        rows = [
            row
            for row in rows
            if row.evidence_type not in {"sensor.read_failed", "rule.failure_count_in_window"}
        ]
    else:
        cause["evidence"][0]["details"][0][missing] = "not-a-matched-identity"
    assert rows  # Real unrelated UUIDs exist, but none can support this criterion.
    assert _candidate_evidence_refs(cause, diagnosis, rows) == []


def test_missing_normalized_event_does_not_fall_back_to_another_source(persisted_facts):
    _, _, _, _, diagnosis, rows, _ = persisted_facts
    cause = {
        "evidence": [
            {
                "fact": "event_type_count",
                "details": [
                    {
                        "event_id": "event:missing",
                        "source": "device_heartbeat",
                        "source_ref": "heartbeat-source",
                    }
                ],
            }
        ]
    }
    assert _candidate_evidence_refs(cause, diagnosis, rows) == []


@pytest.mark.parametrize("refs", [[], ["unrelated"], ["related", "unrelated"]])
@pytest.mark.parametrize("support", ["low", "medium", "high", "unknown"])
def test_model_and_independent_guard_reject_unassociated_evidence(refs, support):
    state = {
        "error_type": "SENSOR_READ_FAILED",
        "fault_tree_candidates": [{"cause_id": "synthetic", "evidence_refs": ["related"]}],
        "evidence_registry": [
            {"id": evidence_id, "fact": "synthetic", "source": "rule", "status": "observed"}
            for evidence_id in ("related", "unrelated")
        ],
    }
    result = {
        "error_type": "SENSOR_READ_FAILED",
        "conclusion": "ranked",
        "ranked_causes": [
            {
                "cause_id": "synthetic",
                "cause": "合成候选",
                "used_evidence_ids": refs,
                "support_level": support,
                "reason": "合成软件反例，不能用作硬件结论。",
            }
        ],
        "summary": "合成软件反例。",
    }
    with pytest.raises(ValueError, match="evidence"):
        _validate_reasoning(json.dumps(result), state, state["evidence_registry"])
    checked = validate_reasoning_against_knowledge(
        {**state, "reasoned_causes": result["ranked_causes"]}
    )
    assert checked["checks"]["candidate_evidence_associated"] is False
    assert checked["status"] == "rejected"


def test_legacy_candidate_without_links_requires_unknown():
    state = {
        "error_type": "SENSOR_READ_FAILED",
        "fault_tree_candidates": [{"cause_id": "legacy", "score": 0.9}],
        "evidence_registry": [{"id": "unrelated", "fact": "synthetic", "source": "rule"}],
    }
    result = _fallback_reasoning(state, limitation="synthetic")
    assert result.conclusion == "unknown"
    assert result.ranked_causes == []
    assert (
        _validate_reasoning(result.model_dump_json(), state, state["evidence_registry"]) == result
    )
    checked = validate_reasoning_against_knowledge({**state, "reasoned_causes": []})
    assert checked["checks"]["candidate_evidence_associated"] is True
