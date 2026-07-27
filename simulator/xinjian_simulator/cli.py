import argparse
import json
import os
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from uuid import UUID, uuid4

from xinjian_simulator.client import DeviceApiClient
from xinjian_simulator.config import SimulationConfig
from xinjian_simulator.dsl import DslScenario, list_specs, load_spec
from xinjian_simulator.runner import run_scenario
from xinjian_simulator.scenarios import SCENARIO_FACTORIES

REPORT_DIRECTORY = Path(".simulator-runs")


def _legacy_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run one compatibility simulator scenario")
    parser.add_argument("--iterations", type=int)
    parser.add_argument("--interval-seconds", type=float)
    return parser


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Versioned synthetic virtual laboratory")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("list", help="List bundled scenario specifications")
    validate = commands.add_parser(
        "validate",
        help="Validate one scenario or all bundled scenarios",
    )
    validate.add_argument("scenario", nargs="?")
    run = commands.add_parser("run", help="Run a scenario specification")
    run.add_argument("scenario")
    run.add_argument("--iterations", type=int)
    run.add_argument("--interval-seconds", type=float)
    replay = commands.add_parser("replay", help="Replay a prior run with the same spec and cycles")
    replay.add_argument("test_run_id")
    report = commands.add_parser("report", help="Print one local synthetic run report")
    report.add_argument("test_run_id")
    cleanup = commands.add_parser("cleanup", help="Delete only data tagged by one synthetic run")
    cleanup.add_argument("test_run_id")
    return parser


def _validated_run_id(value: str) -> str:
    try:
        return str(UUID(value))
    except ValueError as error:
        raise SystemExit("test_run_id must be a UUID") from error


def _report_path(test_run_id: str) -> Path:
    return REPORT_DIRECTORY / f"{_validated_run_id(test_run_id)}.json"


def _load_report(test_run_id: str) -> dict:
    path = _report_path(test_run_id)
    if not path.is_file():
        raise SystemExit(f"run report not found: {test_run_id}")
    return json.loads(path.read_text(encoding="utf-8"))


def _configs_for_devices(spec_devices: int, interval: Optional[float]) -> list[SimulationConfig]:
    base = SimulationConfig.from_env()
    if interval is not None:
        if interval <= 0:
            raise SystemExit("--interval-seconds must be positive")
        base = replace(base, interval_seconds=interval)
    if spec_devices == 1:
        return [base]
    device_ids = [item.strip() for item in os.getenv("XINJIAN_DEVICE_IDS", "").split(",") if item]
    tokens = [item.strip() for item in os.getenv("XINJIAN_DEVICE_TOKENS", "").split(",") if item]
    if len(device_ids) != spec_devices or len(tokens) != spec_devices:
        raise SystemExit(
            "multi-device scenario requires XINJIAN_DEVICE_IDS and XINJIAN_DEVICE_TOKENS "
            f"with exactly {spec_devices} comma-separated values"
        )
    return [
        replace(base, device_id=device_id, device_token=token)
        for device_id, token in zip(device_ids, tokens)
    ]


def _execute_spec(
    scenario_reference: str,
    *,
    iterations: Optional[int],
    interval_seconds: Optional[float],
    replay_of: Optional[str] = None,
) -> dict:
    spec = load_spec(scenario_reference)
    cycles = iterations if iterations is not None else len(spec.cycles)
    if cycles < 1:
        raise SystemExit("--iterations must be positive")
    configs = _configs_for_devices(spec.devices, interval_seconds)
    test_run_id = str(uuid4())
    device_reports = []
    for config in configs:
        device_reports.append(
            {
                "device_id": config.device_id,
                **run_scenario(
                    DslScenario(spec),
                    config,
                    cycles,
                    test_run_id=test_run_id,
                ),
            }
        )
    report = {
        "report_schema_version": "1",
        "test_run_id": test_run_id,
        "scenario_id": spec.scenario_id,
        "scenario_version": spec.version,
        "scenario_hash": spec.content_hash,
        "seed": spec.seed,
        "is_test_data": True,
        "status": "completed",
        "cycles": cycles,
        "replay_of": replay_of,
        "completed_at": datetime.now(timezone.utc).isoformat(),
        "devices": device_reports,
    }
    REPORT_DIRECTORY.mkdir(exist_ok=True)
    _report_path(test_run_id).write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return report


def _run_legacy(default_scenario: str) -> None:
    args = _legacy_parser().parse_args()
    if args.iterations is not None and args.iterations < 1:
        raise SystemExit("--iterations must be positive")
    config = SimulationConfig.from_env()
    if args.interval_seconds is not None:
        config = replace(config, interval_seconds=args.interval_seconds)
    run_scenario(SCENARIO_FACTORIES[default_scenario](), config, args.iterations)


def main(default_scenario: Optional[str] = None) -> None:
    if default_scenario is not None:
        _run_legacy(default_scenario)
        return
    args = build_parser().parse_args()
    try:
        if args.command == "list":
            for spec in list_specs():
                print(
                    f"{spec.scenario_id}\tversion={spec.version}\tdevices={spec.devices}\t"
                    f"seed={spec.seed}\t{spec.title}"
                )
            return
        if args.command == "validate":
            specs = [load_spec(args.scenario)] if args.scenario else list_specs()
            for spec in specs:
                print(f"valid scenario={spec.scenario_id} hash={spec.content_hash}")
            return
        if args.command == "report":
            print(json.dumps(_load_report(args.test_run_id), ensure_ascii=False, indent=2))
            return
        if args.command == "replay":
            previous = _load_report(args.test_run_id)
            result = _execute_spec(
                previous["scenario_id"],
                iterations=previous["cycles"],
                interval_seconds=None,
                replay_of=previous["test_run_id"],
            )
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return
        if args.command == "cleanup":
            report = _load_report(args.test_run_id)
            configs = _configs_for_devices(len(report["devices"]), None)
            results = []
            for config in configs:
                with DeviceApiClient(config) as client:
                    results.append(client.cleanup_test_run(report["test_run_id"]))
            report["cleanup"] = results
            report["status"] = "cleaned"
            _report_path(report["test_run_id"]).write_text(
                json.dumps(report, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            print(json.dumps({"test_run_id": report["test_run_id"], "cleanup": results}))
            return
        result = _execute_spec(
            args.scenario,
            iterations=args.iterations,
            interval_seconds=args.interval_seconds,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except ValueError as error:
        raise SystemExit(str(error)) from error


if __name__ == "__main__":
    main()
