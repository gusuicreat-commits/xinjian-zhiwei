from datetime import datetime, timezone

from xinjian_simulator.config import SimulationConfig
from xinjian_simulator.dsl import DslScenario, list_specs, load_spec


def _config() -> SimulationConfig:
    return SimulationConfig(
        api_base_url="http://testserver",
        device_id="synthetic-device",
        device_token="synthetic-token",
    )


def test_all_bundled_scenarios_validate_and_are_versioned() -> None:
    specs = list_specs()

    assert {spec.scenario_id for spec in specs} == {
        "normal",
        "read-failure",
        "offline",
        "out-of-range",
        "value-stuck",
        "intermittent-failure",
        "recovery",
        "multi-device-classroom",
        "multi-anomaly",
        "wifi-jitter",
    }
    assert all(spec.schema_version == "1" and spec.version == "1.0" for spec in specs)
    assert all(len(spec.content_hash) == 64 for spec in specs)


def test_offline_network_cycle_drops_upload_deterministically() -> None:
    scenario = DslScenario(load_spec("offline"))
    now = datetime.now(timezone.utc)

    first = scenario.next_actions(_config(), now)
    second = scenario.next_actions(_config(), now)
    repeated = scenario.next_actions(_config(), now)

    assert first
    assert second == []
    assert [action.kind for action in repeated] == [action.kind for action in first]


def test_recovery_timeline_moves_from_failure_to_normal_reading() -> None:
    scenario = DslScenario(load_spec("recovery"))
    now = datetime.now(timezone.utc)

    failed = scenario.next_actions(_config(), now)
    recovered = scenario.next_actions(_config(), now)

    assert any(action.payload.get("event_code") == "SENSOR_READ_FAILED" for action in failed)
    assert any(action.kind == "reading" for action in recovered)


def test_multi_device_classroom_declares_three_devices() -> None:
    assert load_spec("multi-device-classroom").devices == 3


def test_wifi_jitter_has_delay_drop_and_recovery_cycles() -> None:
    scenario = DslScenario(load_spec("wifi-jitter"))
    now = datetime.now(timezone.utc)

    first = scenario.next_actions(_config(), now)
    first_latency = scenario.network_latency_seconds
    dropped = scenario.next_actions(_config(), now)
    recovered = scenario.next_actions(_config(), now)
    recovered_latency = scenario.network_latency_seconds

    assert first and first_latency > 0
    assert dropped == []
    assert recovered and recovered_latency > first_latency


def test_multi_anomaly_emits_read_failure_and_out_of_range_evidence() -> None:
    actions = DslScenario(load_spec("multi-anomaly")).next_actions(
        _config(),
        datetime.now(timezone.utc),
    )
    codes = {action.payload.get("event_code") for action in actions}

    assert {"SENSOR_READ_FAILED", "VALUE_OUT_OF_RANGE"} <= codes
    assert sum(action.kind == "reading" for action in actions) == 2
