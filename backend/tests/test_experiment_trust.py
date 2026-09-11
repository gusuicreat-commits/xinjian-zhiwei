from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import UUID

import pytest
from pydantic import ValidationError
from sqlalchemy import select

from app.diagnosis.expected_behavior import compare_expected_behaviors
from app.diagnosis.normalization import normalize_legacy_context
from app.diagnosis.schemas import ContextHeartbeat, ContextLog, RawDeviceRecord
from app.experiment_packages.loader import (
    ExperimentPackageLoadError,
    load_experiment_package,
    load_experiment_package_payload,
    package_documents,
    package_rule_document,
    package_to_experiment_definition,
)
from app.models import Device, DiagnosisEvidence
from app.schemas.knowledge_case import KnowledgeCaseDefinition
from app.services.diagnosis import build_raw_diagnosis_context, diagnose, save_diagnosis_result

ROOT = Path(__file__).resolve().parents[1] / "experiment_packages"
NOW = datetime(2026, 9, 9, tzinfo=timezone.utc)


def context_for(name, payloads=()):
    bundle, _ = load_experiment_package(ROOT / name)
    context = build_raw_diagnosis_context(
        device_id="synthetic-trust",
        definition=package_to_experiment_definition(bundle),
        records=[
            RawDeviceRecord(id=f"r-{i}", source="sensor_reading", payload=p, received_at=NOW)
            for i, p in enumerate(payloads)
        ],
        evaluated_at=NOW,
        last_seen_at=NOW,
    )
    context.package_rule_document = package_rule_document(bundle)
    context.heartbeats = [
        ContextHeartbeat(id="heartbeat", observed_at=NOW, received_at=NOW, is_test_data=True)
    ]
    return bundle, context


@pytest.mark.parametrize("name", ["dht11_temperature_humidity", "gpio_led_output"])
def test_unverified_cases_cannot_claim_approval(name):
    bundle, _ = context_for(name)
    case = bundle.cases.cases[0]
    assert case.source_type == "test_data" and case.review_status == "draft"
    assert case.root_cause_status == "unknown" and case.confirmed_by is None
    raw = case.model_dump(by_alias=True)
    raw["reviewStatus"] = "approved"
    with pytest.raises(ValidationError, match="unverified"):
        KnowledgeCaseDefinition.model_validate(raw)


def test_window_failure_count_does_not_claim_consecutive_failures():
    payloads = []
    for _ in range(5):
        payloads.extend(
            [
                {"error_code": "DHT11_READ_FAILED"},
                {"sensor": "dht11", "metric": "temperature", "value": 25},
            ]
        )
    _, context = context_for("dht11_temperature_humidity", payloads)
    outcome = diagnose(context)
    match = next(m for m in outcome.matches if m.error_type == "SENSOR_READ_FAILED")
    assert match.evidence[0].fact == "failure_count_in_window"
    assert match.evidence[0].observed_value == 5
    assert match.evidence[0].details[-1]["consecutive_failure_count"] is None
    assert "累计" in match.summary


@pytest.mark.parametrize("name", ["dht11_temperature_humidity", "gpio_led_output"])
def test_common_health_checks_are_shared_and_missing_data_is_not_normal(name):
    bundle, context = context_for(name)
    assert not {"DEVICE_OFFLINE", "HEARTBEAT_STALE", "DATA_STALE"} & {
        r.error_type for r in bundle.rules.rules
    }
    assert diagnose(context).matches == []  # Data period is deliberately unconfigured.
    assert context.normal_assessment["status"] == "unknown"
    for required in context.runtime_expectations.required_observations:
        required.maximum_age_seconds = 10  # Synthetic test setting, not hardware calibration.
    errors = {m.error_type for m in diagnose(context).matches}
    assert errors == {"DATA_STALE"}
    context.heartbeats = []
    assert "HEARTBEAT_STALE" in {m.error_type for m in diagnose(context).matches}
    context.last_seen_at = NOW - timedelta(seconds=100)
    assert "DEVICE_OFFLINE" in {m.error_type for m in diagnose(context).matches}


def normal_dht():
    payloads = [
        {
            "sensor": "dht11",
            "metric": m,
            "value": v,
            "timestamp": (NOW - timedelta(seconds=age)).isoformat(),
        }
        for age in (5, 0)
        for m, v in (("temperature", 25), ("humidity", 50))
    ]
    _, context = context_for("dht11_temperature_humidity", payloads)
    for r in context.runtime_expectations.required_observations:
        r.maximum_age_seconds = 10
    return context


def test_normal_requires_heartbeat_periodic_valid_data_and_no_rule_hits():
    context = normal_dht()
    assert not diagnose(context).matches
    assert context.normal_assessment["status"] == "normal"
    context.observations[-1].value = float("nan")
    diagnose(context)
    assert context.normal_assessment["status"] == "abnormal"
    context = normal_dht()
    context.evaluated_at += timedelta(seconds=11)
    assert "DATA_STALE" in {m.error_type for m in diagnose(context).matches}
    context = normal_dht()
    context.observations[0].observed_at -= timedelta(seconds=30)
    assert "DATA_STALE" in {m.error_type for m in diagnose(context).matches}
    context = normal_dht()
    context.heartbeats = []
    diagnose(context)
    assert context.normal_assessment["status"] != "normal"


def test_single_sample_and_unconfigured_period_are_not_periodic_success():
    context = normal_dht()
    context.observations = context.observations[-2:]
    diagnose(context)
    assert context.normal_assessment["status"] == "unknown"
    context = normal_dht()
    context.runtime_expectations.required_observations[0].maximum_age_seconds = None
    diagnose(context)
    assert context.normal_assessment["status"] == "unknown"


def led_payload(metric, value, source, command_id="command-1"):
    return {
        "metric": metric,
        "value": value,
        "measurement_source": source,
        "command_id": command_id,
        "timestamp": NOW.isoformat(),
    }


@pytest.mark.parametrize("value", [0, 1])
def test_led_legacy_level_never_establishes_command_actual_or_light(value):
    _, context = context_for("gpio_led_output", [{"pin": 2, "level": value}])
    assert context.observations[0].metric == "level"
    assert context.observations[0].status == "unknown"
    assert compare_expected_behaviors(context)[0].status == "unknown"
    assert not diagnose(context).matches
    assert context.normal_assessment["status"] == "unknown"


@pytest.mark.parametrize("value", [0, 1])
def test_led_low_and_high_are_compared_to_same_command_not_fixed_high(value):
    _, context = context_for(
        "gpio_led_output",
        [
            led_payload("gpio_command_level", value, "command"),
            led_payload("gpio_actual_level", value, "electrical_measurement"),
        ],
    )
    context.expected_behaviors[0].within_seconds = 5  # Synthetic validation window only.
    assert compare_expected_behaviors(context)[0].status == "satisfied"
    assert not diagnose(context).matches
    assert all(o.metric != "led_physically_on" for o in context.observations)
    context.observations[-1].value = 1 - value
    assert "GPIO_EXPECTATION_FAILED" in {m.error_type for m in diagnose(context).matches}
    context.observations[-1].raw_payload["command_id"] = "other-command"
    assert compare_expected_behaviors(context)[0].status == "unknown"


def test_led_unverified_measurement_and_stale_command_are_unknown():
    _, context = context_for(
        "gpio_led_output",
        [
            led_payload("gpio_command_level", 1, "command"),
            led_payload("gpio_actual_level", 1, "command"),
            led_payload("led_physically_on", 1, "electrical_measurement"),
        ],
    )
    assert [o.status for o in context.observations] == ["normal", "unknown", "unknown"]
    context.expected_behaviors[0].within_seconds = 5
    assert compare_expected_behaviors(context)[0].status == "unknown"


def test_declared_evidence_types_must_match_runtime_names():
    bundle, _ = context_for("gpio_led_output")
    docs = package_documents(bundle)
    docs["hardware.yaml"]["evidence_mapping"][0]["evidence_type"] = "led.output_level"
    with pytest.raises(ExperimentPackageLoadError, match="evidence.runtime_types"):
        load_experiment_package_payload(docs)


def test_led_evidence_persists_distinct_types_and_real_uuids(api_context):
    bundle, context = context_for(
        "gpio_led_output",
        [
            {"pin": 2, "level": 1},
            led_payload("gpio_command_level", 1, "command"),
            led_payload("gpio_actual_level", 1, "electrical_measurement"),
            led_payload("led_physically_on", 1, "optical_observation"),
        ],
    )
    with api_context["session_factory"]() as db:
        result = save_diagnosis_result(
            db, db.scalar(select(Device).limit(1)), context, diagnose(context)
        )
        rows = list(
            db.scalars(select(DiagnosisEvidence).where(DiagnosisEvidence.diagnosis_id == result.id))
        )
        declared = {m.evidence_type for m in bundle.hardware.evidence_mapping}
        assert {r.evidence_type for r in rows} == declared
        for row in rows:
            UUID(row.id)
            assert row.raw_payload
        legacy = next(r for r in rows if r.evidence_type == "observation.level")
        assert legacy.normalized_value["status"] == "unknown"
        assert result.context_snapshot["normal_assessment"]["status"] == "unknown"


def test_legacy_log_preserves_nested_component_identity():
    bundle, _ = context_for("dht11_temperature_humidity")
    result = normalize_legacy_context(
        logs=[
            ContextLog(
                id="synthetic",
                level="error",
                message="test",
                event_code="DHT11_READ_FAILED",
                occurred_at=NOW,
                is_test_data=True,
                raw_payload={"sensor_snapshot": {"component_id": "dht11"}},
            )
        ],
        heartbeats=[],
        readings=[],
        definition=package_to_experiment_definition(bundle),
    )
    assert result.events[0].component_id == "dht11"
    assert result.events[0].interface_id == "dht11_gpio"


@pytest.mark.parametrize("name", ["dht11_temperature_humidity", "gpio_led_output"])
def test_http_ingest_to_package_evidence_uses_same_semantics(api_context, name):
    from uuid import uuid4

    from app.models import User
    from app.services.diagnosis import build_diagnosis_context
    from app.services.experiment_packages import (
        import_experiment_package,
        transition_experiment_package,
    )

    bundle, _ = context_for(name)
    now = datetime.now(timezone.utc)
    if name.startswith("dht"):
        records = [
            {
                "type": "log",
                "payload": {
                    "level": "error",
                    "message": "synthetic read failure",
                    "event_code": "DHT11_READ_FAILED",
                    "sensor_snapshot": {"component_id": "dht11"},
                },
            }
            for _ in range(5)
        ]
    else:
        records = [
            {
                "type": "reading",
                "payload": {
                    "sensor_type": "status_led",
                    "metric_key": metric,
                    "value": 1,
                    "metadata": {"measurement_source": source, "command_id": "synthetic-command"},
                },
            }
            for metric, source in (
                ("level", "unknown"),
                ("gpio_command_level", "command"),
                ("gpio_actual_level", "electrical_measurement"),
            )
        ]
    records.append({"type": "heartbeat", "payload": {"metadata": {}}})
    batch = {
        "protocolVersion": "1.0",
        "schemaVersion": "1",
        "requestId": str(uuid4()),
        "bootId": "trust-test",
        "sequenceNo": 1,
        "sentAt": now.isoformat(),
        "isTestData": True,
        "records": [{**r, "occurredAt": now.isoformat()} for r in records],
    }
    response = api_context["client"].post(
        "/api/v1/device/ingest", headers=api_context["headers"], json=batch
    )
    assert response.status_code == 201
    with api_context["session_factory"]() as db:
        actor = User(
            username="trust-publisher",
            display_name="synthetic test",
            password_hash="test-only",
            is_test_data=True,
        )
        db.add(actor)
        db.flush()
        _, version = import_experiment_package(db, actor, package_documents(bundle))
        assert version.is_test_data  # A caller cannot strip the package's test provenance.
        for status in ("pending", "approved", "published"):
            transition_experiment_package(db, actor, version, status)
        device = db.scalar(select(Device).limit(1))
        context = build_diagnosis_context(
            db, device, experiment_version_id=version.id, evaluated_at=now + timedelta(seconds=1)
        )
        outcome = diagnose(context)
        result = save_diagnosis_result(db, device, context, outcome)
        rows = list(
            db.scalars(select(DiagnosisEvidence).where(DiagnosisEvidence.diagnosis_id == result.id))
        )
        if name.startswith("dht"):
            assert {m.error_type for m in outcome.matches} == {"SENSOR_READ_FAILED"}
            failures = [e for e in rows if e.evidence_type == "sensor.read_failed"]
            assert len(failures) == 5
            assert all(e.normalized_value["component_id"] == "dht11" for e in failures)
        else:
            by_type = {r.evidence_type: r for r in rows}
            assert by_type["observation.level"].normalized_value["status"] == "unknown"
            assert by_type["observation.gpio_command_level"].normalized_value["status"] == "normal"
            assert by_type["observation.gpio_actual_level"].normalized_value["status"] == "normal"
            assert "observation.led_physically_on" not in by_type
        assert all(UUID(r.id) and r.experiment_version_id == version.id for r in rows)


@pytest.mark.parametrize(
    "metric,source",
    [
        ("gpio_command_level", "command"),
        ("gpio_actual_level", "electrical_measurement"),
        ("led_physically_on", "optical_observation"),
    ],
)
def test_led_explicit_metric_with_pin_does_not_match_legacy_mapping(metric, source):
    _, context = context_for("gpio_led_output", [{**led_payload(metric, 1, source), "pin": 2}])
    assert len(context.observations) == 1
    assert context.observations[0].metric == metric
    assert not context.unknown_raw_data
