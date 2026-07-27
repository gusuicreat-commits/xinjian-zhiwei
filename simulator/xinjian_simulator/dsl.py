import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from xinjian_simulator.actions import UploadAction
from xinjian_simulator.config import SimulationConfig
from xinjian_simulator.scenarios import (
    _heartbeat,
    _log,
    _reading,
)

SPEC_DIRECTORY = Path(__file__).resolve().parent.parent / "scenario_specs"
ALLOWED_ACTIONS = {
    "heartbeat",
    "normal-log",
    "read-failure-log",
    "out-of-range-log",
    "primary-normal-reading",
    "secondary-normal-reading",
    "primary-out-of-range-reading",
    "secondary-out-of-range-reading",
    "primary-stuck-reading",
}


@dataclass(frozen=True)
class ScenarioSpec:
    schema_version: str
    scenario_id: str
    version: str
    title: str
    seed: int
    devices: int
    cycles: list[dict[str, Any]]
    source_path: Path
    content_hash: str


def _validate(raw: object, source_path: Path) -> ScenarioSpec:
    if not isinstance(raw, dict):
        raise ValueError("scenario document must be an object")
    required = {"schema_version", "id", "version", "title", "seed", "devices", "cycles"}
    missing = sorted(required - raw.keys())
    if missing:
        raise ValueError(f"missing scenario fields: {', '.join(missing)}")
    if raw["schema_version"] != "1":
        raise ValueError("only scenario schema_version 1 is supported")
    if not isinstance(raw["seed"], int):
        raise ValueError("seed must be an integer")
    if not isinstance(raw["devices"], int) or raw["devices"] < 1:
        raise ValueError("devices must be a positive integer")
    if not isinstance(raw["cycles"], list) or not raw["cycles"]:
        raise ValueError("cycles must be a non-empty list")
    for index, cycle in enumerate(raw["cycles"]):
        if not isinstance(cycle, dict):
            raise ValueError(f"cycle {index} must be an object")
        actions = cycle.get("actions", [])
        if not isinstance(actions, list):
            raise ValueError(f"cycle {index} actions must be a list")
        unknown = sorted(set(actions) - ALLOWED_ACTIONS)
        if unknown:
            raise ValueError(f"cycle {index} has unknown actions: {', '.join(unknown)}")
        network = cycle.get("network", {})
        if not isinstance(network, dict):
            raise ValueError(f"cycle {index} network must be an object")
        if set(network) - {"drop", "latency_ms"}:
            raise ValueError(f"cycle {index} has unsupported network fields")
        if int(network.get("latency_ms", 0)) < 0:
            raise ValueError(f"cycle {index} latency_ms must not be negative")
    canonical = yaml.safe_dump(raw, allow_unicode=True, sort_keys=True)
    return ScenarioSpec(
        schema_version="1",
        scenario_id=str(raw["id"]),
        version=str(raw["version"]),
        title=str(raw["title"]),
        seed=raw["seed"],
        devices=raw["devices"],
        cycles=raw["cycles"],
        source_path=source_path,
        content_hash=hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
    )


def load_spec(reference: str) -> ScenarioSpec:
    candidate = Path(reference)
    if not candidate.exists():
        candidate = SPEC_DIRECTORY / f"{reference}.yaml"
    if not candidate.is_file():
        raise ValueError(f"scenario not found: {reference}")
    return _validate(yaml.safe_load(candidate.read_text(encoding="utf-8")), candidate)


def list_specs() -> list[ScenarioSpec]:
    return [load_spec(str(path)) for path in sorted(SPEC_DIRECTORY.glob("*.yaml"))]


class DslScenario:
    def __init__(self, spec: ScenarioSpec) -> None:
        self.spec = spec
        self.name = spec.scenario_id
        self._cycle = 0
        self.network_latency_seconds = 0.0

    def next_actions(self, config: SimulationConfig, now: Any) -> list[UploadAction]:
        cycle = self.spec.cycles[self._cycle % len(self.spec.cycles)]
        self._cycle += 1
        network = cycle.get("network", {})
        self.network_latency_seconds = int(network.get("latency_ms", 0)) / 1000
        if network.get("drop", False):
            return []
        actions = []
        for action in cycle.get("actions", []):
            actions.extend(self._action(config, now, action))
        return actions

    def _action(
        self,
        config: SimulationConfig,
        now: Any,
        action: str,
    ) -> list[UploadAction]:
        if action == "heartbeat":
            return [_heartbeat(config, now, self.name)]
        if action == "normal-log":
            return [_log(now, "info", "TEST_NORMAL_CYCLE", "Synthetic normal cycle", self.name)]
        if action == "read-failure-log":
            return [
                _log(
                    now,
                    "error",
                    "SENSOR_READ_FAILED",
                    "Synthetic read failure",
                    self.name,
                )
            ]
        if action == "out-of-range-log":
            return [
                _log(
                    now,
                    "warning",
                    "VALUE_OUT_OF_RANGE",
                    "Synthetic out-of-range value",
                    self.name,
                )
            ]
        metric_map = {
            "primary-normal-reading": (
                config.primary_metric_key,
                config.normal_primary_value,
                config.primary_unit,
            ),
            "secondary-normal-reading": (
                config.secondary_metric_key,
                config.normal_secondary_value,
                config.secondary_unit,
            ),
            "primary-out-of-range-reading": (
                config.primary_metric_key,
                config.out_of_range_primary_value,
                config.primary_unit,
            ),
            "secondary-out-of-range-reading": (
                config.secondary_metric_key,
                config.out_of_range_secondary_value,
                config.secondary_unit,
            ),
            "primary-stuck-reading": (
                config.primary_metric_key,
                config.stuck_value,
                config.primary_unit,
            ),
        }
        metric_key, value, unit = metric_map[action]
        return [_reading(config, now, metric_key, value, unit, self.name)]
