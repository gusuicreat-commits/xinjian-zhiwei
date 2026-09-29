"""Reviewed DHT11 content expectations, independent of registry generation."""

import hashlib
import re

import pytest
from test_experiment_packages import PACKAGE_ROOT

from app.experiment_packages.loader import load_experiment_package
from app.services.teaching_materials import select_teaching_materials


@pytest.mark.parametrize(
    "cause",
    [
        "wiring.data_pin_mismatch",
        "software.gpio_mismatch",
        "hardware.sensor_failure",
    ],
)
@pytest.mark.parametrize("level", [1, 2, 3, 4])
def test_dht11_guidance_explains_record_identity_and_measurement_semantics(cause, level):
    bundle, _ = load_experiment_package(PACKAGE_ROOT / "dht11_temperature_humidity")
    result = select_teaching_materials(
        bundle,
        tree_id="dht11-read-failure-v2",
        cause_id=cause,
        level=level,
        scope={"kind": "component", "keys": ["dht11"]},
    )
    steps = [s["step_id"] for s in result["steps"]]
    assert steps[0] == "identify" and steps.count("identify") == 1
    assert "dht11.protocol_evidence" in [c["concept_id"] for c in result["concepts"]]
    assert "actions" not in result


def test_project_interval_is_distinct_from_vendor_exclusive_boundary():
    bundle, _ = load_experiment_package(PACKAGE_ROOT / "dht11_temperature_humidity")
    params = bundle.hardware.interfaces[0].parameters
    assert params["configured_sample_interval_ms"] == params["minimum_interval_ms"] == 3000
    assert bundle.hardware.required_parameters["minimum_interval_ms"] == 3000
    config = (
        PACKAGE_ROOT.parents[1] / "firmware/esp32_dht11/include/firmware_config.h"
    ).read_text()
    assert int(re.search(r"XJ_SAMPLE_INTERVAL_MS = (\d+)UL", config)[1]) == 3000


def test_vendor_claims_have_direct_located_sources_not_only_old_yaml():
    bundle, _ = load_experiment_package(PACKAGE_ROOT / "dht11_temperature_humidity")
    registry = bundle.metadata.content_registry
    sources = {s.source_id: s for s in registry.sources}
    manual = sources["aosong-dht11-v1.3"]
    assert manual.kind == "vendor_document" and manual.revision == "V1.3_20170331"
    assert manual.sha256 == "1702de1e17328b98275d381404d27592b3f8da274b27df30b6caf42e6d3b0f16"
    units = {u.unit_id: u for u in registry.units}
    for key in (
        "concept.dht11.minimum_interval",
        "concept.dht11.single_bus",
        "concept.dht11.protocol_evidence",
    ):
        assert any(
            ref.source_id == manual.source_id and ref.locator for ref in units[key].source_refs
        )
    assert sources["pending.hardware"].availability == "pending"
    assert sources["pending.teacher"].availability == "pending"
    assert sources["pending.course"].availability == "pending"


def test_registered_firmware_sources_match_delivered_files():
    bundle, _ = load_experiment_package(PACKAGE_ROOT / "dht11_temperature_humidity")
    sources = [
        s for s in bundle.metadata.content_registry.sources if s.source_id.startswith("firmware.")
    ]
    assert {s.source_id for s in sources} == {
        "firmware.config",
        "firmware.reader",
        "firmware.main",
        "firmware.build",
    }
    for source in sources:
        raw = (PACKAGE_ROOT.parents[1] / source.location).read_bytes()
        assert hashlib.sha256(raw).hexdigest() == source.sha256


def test_expanded_material_is_scoped_and_has_fixed_local_sources():
    bundle, _ = load_experiment_package(PACKAGE_ROOT / "dht11_temperature_humidity")
    expected = {
        "wiring.data_pin_mismatch": {"dht11.power_and_pullup", "dht11.identity_scope"},
        "software.gpio_mismatch": {"dht11.identity_scope"},
        "hardware.sensor_failure": {"dht11.delivery_evidence", "dht11.recovery_boundary"},
    }
    for cause, ids in expected.items():
        for level in range(1, 5):
            result = select_teaching_materials(
                bundle,
                tree_id="dht11-read-failure-v2",
                cause_id=cause,
                level=level,
                scope={"kind": "component", "keys": ["dht11"]},
            )
            assert ids <= {c["concept_id"] for c in result["concepts"]}
            foreign = select_teaching_materials(
                bundle,
                tree_id="dht11-read-failure-v2",
                cause_id=cause,
                level=level,
                scope={"kind": "component", "keys": ["status_led"]},
            )
            assert foreign == {"concepts": [], "steps": []}
    for source in bundle.metadata.content_registry.sources:
        if source.source_id in {
            "internal.lab-guide",
            "runtime.store",
            "contract.device",
            "contract.health",
        }:
            raw = (PACKAGE_ROOT.parents[1] / source.location).read_bytes()
            assert hashlib.sha256(raw).hexdigest() == source.sha256
