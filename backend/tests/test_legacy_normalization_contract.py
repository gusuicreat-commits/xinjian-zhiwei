"""Package identity inference must preserve the generic stored-log contract."""

from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.diagnosis.normalization import normalize_legacy_context
from app.diagnosis.schemas import ContextLog
from app.experiment_packages.loader import (
    load_experiment_package,
    package_to_experiment_definition,
)
from app.services.diagnosis_episode import _primary_error

ROOT = Path(__file__).resolve().parents[1] / "experiment_packages"
NOW = datetime(2026, 10, 11, tzinfo=timezone.utc)


def definition(name):
    bundle, _ = load_experiment_package(ROOT / name)
    return package_to_experiment_definition(bundle)


def event(package, code, **payload):
    result = normalize_legacy_context(
        logs=[ContextLog(
            id="synthetic-log", level="error", message="synthetic",
            event_code=code, occurred_at=NOW, is_test_data=True,
            raw_payload={"event_code": code, **payload},
        )],
        heartbeats=[], readings=[], definition=package,
    )
    assert not result.unknown_records
    return result.events[0]


@pytest.mark.parametrize("name", ["gpio_led_output", "sht31_temperature_humidity", None])
def test_unmapped_generic_logs_preserve_event_code_and_explicit_identity(name):
    package = definition(name) if name else None
    for code in ("SENSOR_READ_FAILED", "SENSOR_POWER_UNSTABLE"):
        bare = event(package, code)
        assert bare.type == code
        assert bare.component_id is None and bare.interface_id is None
        bound = event(package, code, sensor_snapshot={
            "component_id": "status_led", "interface_id": "led_gpio",
        })
        assert bound.type == code
        assert bound.component_id == "status_led" and bound.interface_id == "led_gpio"


def test_led_logs_keep_existing_component_binding_without_matching_event_mapping():
    package = definition("gpio_led_output")
    mapped_observation = event(package, "SENSOR_READ_FAILED", pin=2)
    assert mapped_observation.type == "SENSOR_READ_FAILED"
    assert mapped_observation.component_id is None
    bound = event(package, "SENSOR_READ_FAILED", sensor_snapshot={"component_id": "status_led"})
    assert bound.type == "SENSOR_READ_FAILED"
    assert bound.component_id == "status_led" and bound.interface_id == "led_gpio"


def test_exactly_one_event_mapping_supplies_only_missing_component_identity():
    package = definition("sht31_temperature_humidity")
    matched = event(package, "SHT31_READ_FAILED", sensor_snapshot={"source": "serial_bridge"})
    assert matched.type == "SHT31_READ_FAILED"  # evidence_mapping is applied later.
    assert matched.component_id == "sht31" and matched.interface_id == "sht31_i2c"
    assert matched.raw_payload["sensor_snapshot"] == {"source": "serial_bridge"}
    explicit = event(package, "SHT31_READ_FAILED", sensor_snapshot={
        "component_id": "explicit", "interface_id": "explicit-interface",
    })
    assert explicit.component_id == "explicit" and explicit.interface_id == "explicit-interface"
    package.normalization.mappings.append(package.normalization.mappings[0].model_copy(
        update={"id": "synthetic-ambiguous-event", "component_id": "other"},
    ))
    ambiguous = event(package, "SHT31_READ_FAILED")
    assert ambiguous.type == "SHT31_READ_FAILED"
    assert ambiguous.component_id is None and ambiguous.interface_id is None


def test_mapped_error_log_below_rule_window_is_not_an_unclassified_issue():
    diagnosis = SimpleNamespace(
        device_id="synthetic",
        evaluated_at=NOW,
        ruleset_version="1",
        ruleset_hash="hash",
        input_fingerprint="fingerprint",
        matched_rules=[],
        evidence=[],
        context_snapshot={
            "logs": [{"id": "log-1", "level": "error", "event_code": "SHT31_READ_FAILED"}],
            "events": [{
                "source": "device_log", "source_ref": "log-1", "type": "sensor.read_failed",
            }],
        },
        experiment_id="sht31_temperature_humidity",
        is_test_data=True,
    )
    assert _primary_error(diagnosis) is None


def test_unmapped_error_log_remains_unclassified():
    diagnosis = SimpleNamespace(
        device_id="synthetic",
        evaluated_at=NOW,
        ruleset_version="1",
        ruleset_hash="hash",
        input_fingerprint="fingerprint",
        matched_rules=[],
        evidence=[],
        context_snapshot={
            "logs": [{"id": "log-1", "level": "error", "event_code": "UNKNOWN_EVENT"}],
            "events": [{
                "source": "device_log", "source_ref": "log-1", "type": "UNKNOWN_EVENT",
            }],
        },
        experiment_id="sht31_temperature_humidity",
        is_test_data=True,
    )
    assert _primary_error(diagnosis) == "UNCLASSIFIED_ANOMALY"
