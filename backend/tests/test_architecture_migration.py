from datetime import datetime, timezone
from pathlib import Path

import pytest

from app.diagnosis.expected_behavior import compare_expected_behaviors
from app.diagnosis.fault_tree import evaluate_fault_tree
from app.diagnosis.fault_tree_loader import load_fault_trees
from app.diagnosis.loader import load_rules
from app.diagnosis.schemas import DiagnosisRunResponse, RawDeviceRecord
from app.experiments.loader import (
    ExperimentDefinitionLoadError,
    load_experiment_definition,
    load_experiment_definitions,
)
from app.models import DiagnosisResult
from app.services.diagnosis import build_raw_diagnosis_context, diagnose

NOW = datetime(2026, 8, 18, 8, 0, tzinfo=timezone.utc)


def definition(experiment_id: str):
    return load_experiment_definition(experiment_id, "1.0")[0]


def raw_context(experiment_id: str, payload: dict):
    selected = definition(experiment_id)
    return build_raw_diagnosis_context(
        device_id=f"fixture-{experiment_id}",
        definition=selected,
        records=[
            RawDeviceRecord(
                id=f"raw-{experiment_id}",
                source="migration_fixture",
                payload=payload,
                received_at=NOW,
            )
        ],
        evaluated_at=NOW,
        last_seen_at=NOW,
    )


def test_three_distinct_experiment_definitions_load_with_stable_versions() -> None:
    loaded = load_experiment_definitions()

    assert {(item.experiment.id, item.experiment.version) for item, _ in loaded} == {
        ("gpio_led_output", "1.0"),
        ("sht31_i2c_temperature", "1.0"),
        ("wifi_data_upload", "1.0"),
    }
    assert all(len(digest) == 64 for _, digest in loaded)


def test_invalid_experiment_configuration_is_rejected_explicitly(tmp_path: Path) -> None:
    (tmp_path / "invalid.yaml").write_text(
        """
schema_version: "1"
experiment: {id: Bad ID, name: invalid, version: "1"}
hardware: {family: test, board_model: test, components: []}
interfaces: []
expected_behaviors: []
unknown_field: forbidden
""",
        encoding="utf-8",
    )

    with pytest.raises(ExperimentDefinitionLoadError, match="invalid experiment definition"):
        load_experiment_definitions(tmp_path)


def test_common_and_interface_rules_are_reused_without_experiment_pollution() -> None:
    gpio = raw_context("gpio_led_output", {"pin": 2, "level": 0})
    i2c = raw_context("sht31_i2c_temperature", {"bus": "i2c", "error": "timeout"})
    wifi = raw_context("wifi_data_upload", {"wifi_connected": False})

    gpio_rules, _ = load_rules(context=gpio)
    i2c_rules, _ = load_rules(context=i2c)
    wifi_rules, _ = load_rules(context=wifi)
    assert "device-offline-v1" in {item.id for item in gpio_rules.rules}
    assert "device-offline-v1" in {item.id for item in i2c_rules.rules}
    assert "gpio-led-expected-state-v1" in {item.id for item in gpio_rules.rules}
    assert "gpio-led-expected-state-v1" not in {item.id for item in i2c_rules.rules}
    assert "gpio-led-expected-state-v1" not in {item.id for item in wifi_rules.rules}
    assert "interface-communication-failure-v1" in {item.id for item in i2c_rules.rules}
    assert "interface-communication-failure-v1" in {item.id for item in wifi_rules.rules}
    assert {
        item.source_id
        for item in [*i2c_rules.rules, *wifi_rules.rules]
        if item.id == "interface-communication-failure-v1"
    } == {"interfaces.communication"}


@pytest.mark.parametrize(
    ("experiment_id", "payload", "expected_error", "normalized_kind"),
    [
        ("gpio_led_output", {"pin": 2, "level": 0}, "GPIO_EXPECTATION_FAILED", "observation"),
        (
            "sht31_i2c_temperature",
            {"bus": "i2c", "error": "timeout"},
            "INTERFACE_COMMUNICATION_FAILURE",
            "event",
        ),
        (
            "wifi_data_upload",
            {"wifi_connected": False},
            "INTERFACE_COMMUNICATION_FAILURE",
            "event",
        ),
    ],
)
def test_different_raw_shapes_use_one_context_and_diagnosis_result_contract(
    experiment_id: str,
    payload: dict,
    expected_error: str,
    normalized_kind: str,
) -> None:
    context = raw_context(experiment_id, payload)
    outcome = diagnose(context)

    assert context.experiment_id == experiment_id
    assert context.experiment_version == "1.0"
    assert context.device is not None
    assert (len(context.observations) == 1) is (normalized_kind == "observation")
    assert (len(context.events) == 1) is (normalized_kind == "event")
    assert [item.error_type for item in outcome.matches] == [expected_error]
    assert outcome.matches[0].source_id in {
        "experiments.gpio_led",
        "interfaces.communication",
    }
    assert context.inference_state.rule_hits
    # The public response schema is identical for GPIO, I2C and network experiments.
    response = DiagnosisRunResponse(
        id="result-id",
        device_id=context.device_id,
        evaluated_at=NOW,
        ruleset_version=outcome.ruleset_version,
        input_fingerprint=outcome.input_fingerprint,
        matches=outcome.matches,
        is_test_data=True,
        created_at=NOW,
        experiment_id=context.experiment_id,
        experiment_version=context.experiment_version,
        knowledge_scope=context.knowledge_scope.model_dump(mode="json"),
    )
    assert response.matches[0].error_type == expected_error


def test_unknown_raw_data_is_preserved_and_marked_unknown() -> None:
    context = raw_context("gpio_led_output", {"vendor_blob": "opaque"})

    assert context.observations == []
    assert len(context.unknown_raw_data) == 1
    assert context.unknown_raw_data[0].raw_payload == {"vendor_blob": "opaque"}
    assert context.events[0].type == "unknown"
    assert context.events[0].status == "unknown"

    incomplete = raw_context("gpio_led_output", {"pin": 2})
    assert incomplete.observations == []
    assert incomplete.unknown_raw_data[0].reason.endswith("missing required data")


def test_expected_behavior_compares_standard_observation_and_event() -> None:
    gpio = raw_context("gpio_led_output", {"pin": 2, "level": 0})
    wifi = raw_context("wifi_data_upload", {"wifi_connected": True})

    assert compare_expected_behaviors(gpio)[0].status == "violated"
    assert compare_expected_behaviors(wifi)[0].status == "satisfied"


def test_fault_tree_loading_is_scoped_and_interface_tree_is_reused() -> None:
    gpio = raw_context("gpio_led_output", {"pin": 2, "level": 0})
    i2c = raw_context("sht31_i2c_temperature", {"bus": "i2c", "error": "timeout"})
    wifi = raw_context("wifi_data_upload", {"wifi_connected": False})

    gpio_trees, _ = load_fault_trees(context=gpio)
    i2c_trees, _ = load_fault_trees(context=i2c)
    wifi_trees, _ = load_fault_trees(context=wifi)
    assert [item.id for item in gpio_trees.trees] == ["gpio-led-output-v1"]
    assert [item.id for item in i2c_trees.trees] == ["interface-communication-failure-v1"]
    assert [item.id for item in wifi_trees.trees] == ["interface-communication-failure-v1"]

    outcome = diagnose(i2c)
    evaluated = evaluate_fault_tree(
        i2c_trees.trees[0],
        i2c,
        outcome,
        failure_count=1,
        anomaly_duration_seconds=0,
    )
    assert evaluated is not None
    assert evaluated.source_id == "interfaces.communication"
    assert evaluated.ranked_causes[0].score == 75


def test_missing_configured_artifact_source_fails_closed() -> None:
    context = raw_context("gpio_led_output", {"pin": 2, "level": 0})
    context.artifact_selection.rule_sources = ["missing.source"]

    with pytest.raises(ValueError, match="not loaded"):
        load_rules(context=context)


def test_existing_fastapi_flow_accepts_definition_reference_and_persists_scope(
    api_context: dict,
) -> None:
    client = api_context["client"]
    headers = api_context["headers"]
    reading = client.post(
        "/api/v1/device/readings",
        headers=headers,
        json={
            "sensor_type": "status_led",
            "metric_key": "level",
            "value": 0,
            "observed_at": NOW.isoformat(),
            "is_test_data": True,
        },
    )
    assert reading.status_code == 201

    response = client.post(
        "/api/v1/diagnosis/devices/phase2-test-device/run",
        headers=headers,
        json={
            "lookback_seconds": 604800,
            "experiment_id": "gpio_led_output",
            "experiment_version": "1.0",
        },
    )

    assert response.status_code == 201
    payload = response.json()
    assert payload["experiment_id"] == "gpio_led_output"
    assert payload["experiment_version"] == "1.0"
    assert payload["knowledge_scope"]["interfaces"] == ["gpio"]
    assert "GPIO_EXPECTATION_FAILED" in {item["error_type"] for item in payload["matches"]}
    with api_context["session_factory"]() as db:
        record = db.get(DiagnosisResult, payload["id"])
        assert record.experiment_definition_hash is not None
        assert record.context_snapshot["observations"][0]["metric"] == "level"


def test_existing_fastapi_flow_rejects_unknown_definition(api_context: dict) -> None:
    response = api_context["client"].post(
        "/api/v1/diagnosis/devices/phase2-test-device/run",
        headers=api_context["headers"],
        json={"experiment_id": "does_not_exist", "experiment_version": "1.0"},
    )

    assert response.status_code == 422
    assert "not found" in response.json()["detail"]
