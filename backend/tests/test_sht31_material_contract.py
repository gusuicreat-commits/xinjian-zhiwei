"""Independent acceptance contracts for SHT31 materials and evidence boundaries."""

import hashlib

import pytest
from test_experiment_packages import PACKAGE_ROOT

from app.experiment_packages.loader import load_experiment_package
from app.services.teaching_materials import select_teaching_materials

CAUSES = (
    "wiring.i2c_lines",
    "wiring.power_ground",
    "wiring.address_mismatch",
    "wiring.pullup_or_length",
    "software.i2c_config",
    "hardware.sensor_failure",
)


@pytest.mark.parametrize("cause", CAUSES)
@pytest.mark.parametrize("level", [1, 2, 3, 4])
def test_guidance_is_scoped_and_keeps_identity_and_protocol_boundaries(cause, level):
    bundle, _ = load_experiment_package(PACKAGE_ROOT / "sht31_temperature_humidity")
    result = select_teaching_materials(
        bundle,
        tree_id="sht31-read-failure-v1",
        cause_id=cause,
        level=level,
        scope={"kind": "component", "keys": ["sht31"]},
    )
    assert [s["step_id"] for s in result["steps"]][0] == "identify"
    assert "sht31.protocol_evidence" in {c["concept_id"] for c in result["concepts"]}
    assert "actions" not in result
    assert select_teaching_materials(
        bundle,
        tree_id="sht31-read-failure-v1",
        cause_id=cause,
        level=level,
        scope={"kind": "component", "keys": ["status_led"]},
    ) == {"concepts": [], "steps": []}


def test_current_i2c_configuration_and_unverified_hardware_contract():
    bundle, _ = load_experiment_package(PACKAGE_ROOT / "sht31_temperature_humidity")
    interface = bundle.hardware.interfaces[0]
    assert interface.type == "i2c" and interface.pins == {"sda": 8, "scl": 9}
    assert interface.parameters["address"] == 0x44
    assert interface.parameters["frequency_hz"] == 100000
    assert interface.parameters["measurement_command"] == 0x2400
    assert interface.parameters["configured_sample_interval_ms"] == 1000
    runtime = bundle.hardware.runtime_expectations
    assert runtime.verification_status == "pending_hardware"
    assert all(r.maximum_age_seconds is None for r in runtime.required_observations)
    assert runtime.heartbeat_maximum_age_seconds is None
    assert set(CAUSES) == {c.id for c in bundle.fault_trees.trees[0].causes}
    assert all("unknown" in c.evidence[0].description for c in bundle.fault_trees.trees[0].causes)
    teaching = bundle.steps.steps
    assert any("关闭 COMTool" in s.expected_state for s in teaching)
    case = bundle.cases.cases[0]
    assert case.source_type == "test_data" and case.root_cause_status == "unknown"
    assert case.review_status == "draft" and case.teacher_notes is None


def test_registered_sources_match_actual_files_and_pending_materials_remain_pending():
    bundle, _ = load_experiment_package(PACKAGE_ROOT / "sht31_temperature_humidity")
    sources = {s.source_id: s for s in bundle.metadata.content_registry.sources}
    manual = sources["sensirion-sht3x-dis-datasheet-v7"]
    assert manual.kind == "vendor_document"
    assert manual.sha256 == "095b1853e7f4328f5897c9ca6c392a7dd8b0202eda66b0a2629f9cb840dd496d"
    for source in sources.values():
        if source.availability == "available":
            raw = (PACKAGE_ROOT.parents[1] / source.location).read_bytes()
            assert hashlib.sha256(raw).hexdigest() == source.sha256
            assert source.revision and source.locator
    for sid in ("pending.hardware", "pending.teacher", "pending.course"):
        assert sources[sid].availability == "pending" and sources[sid].sha256 is None
    for sid in (
        "firmware.main",
        "firmware.build",
        "firmware.component-build",
        "bridge.parser",
        "bridge.mapping",
    ):
        assert sources[sid].kind == "code"
