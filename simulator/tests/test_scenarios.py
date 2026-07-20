from datetime import datetime, timezone

import pytest

from xinjian_simulator.config import SimulationConfig
from xinjian_simulator.scenarios import (
    NormalScenario,
    OfflineScenario,
    OutOfRangeScenario,
    ReadFailureScenario,
    ValueStuckScenario,
)


@pytest.fixture
def config() -> SimulationConfig:
    return SimulationConfig(
        api_base_url="http://testserver",
        device_id="test-device",
        device_token="test-token",
        interval_seconds=0.01,
    )


def assert_test_data(actions: list) -> None:
    assert actions
    assert all(action.payload["is_test_data"] is True for action in actions)


def test_normal_scenario_has_heartbeat_log_and_two_readings(config: SimulationConfig) -> None:
    actions = NormalScenario().next_actions(config, datetime.now(timezone.utc))

    assert_test_data(actions)
    assert [action.kind for action in actions] == ["heartbeat", "log", "reading", "reading"]


def test_read_failure_has_no_fabricated_reading(config: SimulationConfig) -> None:
    actions = ReadFailureScenario().next_actions(config, datetime.now(timezone.utc))

    assert_test_data(actions)
    assert [action.kind for action in actions] == ["heartbeat", "log"]
    assert actions[1].payload["event_code"] == "TEST_SENSOR_READ_FAILED"
    assert actions[1].payload["sensor_snapshot"]["simulation"]["scenario"] == "read-failure"


def test_offline_scenario_suspends_after_initial_cycle(config: SimulationConfig) -> None:
    scenario = OfflineScenario()

    first = scenario.next_actions(config, datetime.now(timezone.utc))
    second = scenario.next_actions(config, datetime.now(timezone.utc))

    assert_test_data(first)
    assert [action.kind for action in first] == ["heartbeat", "log"]
    assert second == []


def test_out_of_range_values_come_from_configuration(config: SimulationConfig) -> None:
    actions = OutOfRangeScenario().next_actions(config, datetime.now(timezone.utc))
    readings = [action.payload for action in actions if action.kind == "reading"]

    assert_test_data(actions)
    assert [reading["value"] for reading in readings] == [999.0, -999.0]
    assert all(reading["sensor_type"] == "generic-test-sensor" for reading in readings)


def test_value_stuck_repeats_the_same_configured_value(config: SimulationConfig) -> None:
    scenario = ValueStuckScenario()
    values = []
    for _ in range(4):
        actions = scenario.next_actions(config, datetime.now(timezone.utc))
        values.extend(action.payload["value"] for action in actions if action.kind == "reading")

    assert values == [config.stuck_value] * 4
