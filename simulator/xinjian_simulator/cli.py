import argparse
from dataclasses import replace
from typing import Optional

from xinjian_simulator.config import SimulationConfig
from xinjian_simulator.runner import run_scenario
from xinjian_simulator.scenarios import SCENARIO_FACTORIES


def build_parser(default_scenario: Optional[str] = None) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Send explicitly marked Phase 3 test data to the device API"
    )
    if default_scenario is None:
        parser.add_argument("scenario", choices=sorted(SCENARIO_FACTORIES))
    parser.add_argument(
        "--iterations",
        type=int,
        help="Number of cycles; omit to run continuously until interrupted",
    )
    parser.add_argument(
        "--interval-seconds",
        type=float,
        help="Override XINJIAN_INTERVAL_SECONDS for this run",
    )
    return parser


def main(default_scenario: Optional[str] = None) -> None:
    args = build_parser(default_scenario).parse_args()
    scenario_name = default_scenario or args.scenario
    if args.iterations is not None and args.iterations < 1:
        raise SystemExit("--iterations must be positive")
    if args.interval_seconds is not None and args.interval_seconds <= 0:
        raise SystemExit("--interval-seconds must be positive")

    try:
        config = SimulationConfig.from_env()
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
    if args.interval_seconds is not None:
        config = replace(config, interval_seconds=args.interval_seconds)

    scenario = SCENARIO_FACTORIES[scenario_name]()
    print(
        f"starting test simulator scenario={scenario.name} "
        f"device_id={config.device_id} interval={config.interval_seconds}s"
    )
    try:
        run_scenario(scenario, config, args.iterations)
    except KeyboardInterrupt:
        print("simulator stopped by user")


if __name__ == "__main__":
    main()
