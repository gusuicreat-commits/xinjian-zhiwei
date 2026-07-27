from datetime import datetime
from typing import Protocol

from xinjian_simulator.actions import UploadAction
from xinjian_simulator.config import SimulationConfig


def _base_payload() -> dict:
    return {"is_test_data": True}


def _heartbeat(config: SimulationConfig, now: datetime, scenario: str) -> UploadAction:
    return UploadAction(
        kind="heartbeat",
        payload={
            **_base_payload(),
            "observed_at": now.isoformat(),
            "firmware_version": config.firmware_version,
            "metadata": {"source": "phase3-simulator", "scenario": scenario},
        },
    )


def _log(now: datetime, level: str, event_code: str, message: str, scenario: str) -> UploadAction:
    return UploadAction(
        kind="log",
        payload={
            **_base_payload(),
            "level": level,
            "message": message,
            "event_code": event_code,
            "occurred_at": now.isoformat(),
            "sensor_snapshot": {"simulation": {"source": "phase3-simulator", "scenario": scenario}},
        },
    )


def _reading(
    config: SimulationConfig,
    now: datetime,
    metric_key: str,
    value: float,
    unit: str,
    scenario: str,
) -> UploadAction:
    return UploadAction(
        kind="reading",
        payload={
            **_base_payload(),
            "sensor_type": config.sensor_type,
            "metric_key": metric_key,
            "value": value,
            "unit": unit,
            "observed_at": now.isoformat(),
            "metadata": {"source": "phase3-simulator", "scenario": scenario},
        },
    )


class Scenario(Protocol):
    name: str

    def next_actions(self, config: SimulationConfig, now: datetime) -> list[UploadAction]: ...


class NormalScenario:
    name = "normal"

    def next_actions(self, config: SimulationConfig, now: datetime) -> list[UploadAction]:
        return [
            _heartbeat(config, now, self.name),
            _log(now, "info", "TEST_NORMAL_CYCLE", "Phase 3 normal test cycle", self.name),
            _reading(
                config,
                now,
                config.primary_metric_key,
                config.normal_primary_value,
                config.primary_unit,
                self.name,
            ),
            _reading(
                config,
                now,
                config.secondary_metric_key,
                config.normal_secondary_value,
                config.secondary_unit,
                self.name,
            ),
        ]


class ReadFailureScenario:
    name = "read-failure"

    def next_actions(self, config: SimulationConfig, now: datetime) -> list[UploadAction]:
        return [
            _heartbeat(config, now, self.name),
            _log(
                now,
                "error",
                "SENSOR_READ_FAILED",
                "Phase 3 simulated sensor read failure",
                self.name,
            ),
        ]


class OfflineScenario:
    name = "offline"

    def __init__(self) -> None:
        self._initialized = False

    def next_actions(self, config: SimulationConfig, now: datetime) -> list[UploadAction]:
        if self._initialized:
            return []
        self._initialized = True
        return [
            _heartbeat(config, now, self.name),
            _log(
                now,
                "warning",
                "TEST_HEARTBEAT_SUSPENDED",
                "Phase 3 simulator will now stop sending heartbeats",
                self.name,
            ),
        ]


class OutOfRangeScenario:
    name = "out-of-range"

    def next_actions(self, config: SimulationConfig, now: datetime) -> list[UploadAction]:
        return [
            _heartbeat(config, now, self.name),
            _log(
                now,
                "warning",
                "VALUE_OUT_OF_RANGE",
                "Phase 3 simulated out-of-range values",
                self.name,
            ),
            _reading(
                config,
                now,
                config.primary_metric_key,
                config.out_of_range_primary_value,
                config.primary_unit,
                self.name,
            ),
            _reading(
                config,
                now,
                config.secondary_metric_key,
                config.out_of_range_secondary_value,
                config.secondary_unit,
                self.name,
            ),
        ]


class ValueStuckScenario:
    name = "value-stuck"

    def next_actions(self, config: SimulationConfig, now: datetime) -> list[UploadAction]:
        return [
            _heartbeat(config, now, self.name),
            _log(
                now,
                "warning",
                "TEST_VALUE_STUCK_SAMPLE",
                "Phase 3 repeated-value sample",
                self.name,
            ),
            _reading(
                config,
                now,
                config.primary_metric_key,
                config.stuck_value,
                config.primary_unit,
                self.name,
            ),
        ]


SCENARIO_FACTORIES = {
    "normal": NormalScenario,
    "read-failure": ReadFailureScenario,
    "offline": OfflineScenario,
    "out-of-range": OutOfRangeScenario,
    "value-stuck": ValueStuckScenario,
}
