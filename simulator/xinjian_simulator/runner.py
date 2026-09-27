import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from uuid import UUID, uuid4

from xinjian_simulator.client import DeviceApiClient
from xinjian_simulator.config import SimulationConfig
from xinjian_simulator.reports import save_report
from xinjian_simulator.scenarios import Scenario


def run_scenario(
    scenario: Scenario,
    config: SimulationConfig,
    iterations: Optional[int] = None,
    test_run_id: Optional[str] = None,
    progress=None,
) -> dict[str, object]:
    completed = 0
    resolved_test_run_id = str(UUID(test_run_id)) if test_run_id else str(uuid4())
    record_ids: list[str] = []
    if iterations is not None and iterations < 1:
        raise ValueError("iterations must be positive")

    def persist(status):
        snapshot = {
            "test_run_id": resolved_test_run_id,
            "device_id": config.device_id,
            "scenario": scenario.name,
            "cycles": completed,
            "record_ids": list(record_ids),
            "status": status,
            "is_test_data": True,
        }
        if progress:
            progress(snapshot)
        else:
            save_report(
                Path(".simulator-runs") / f"{resolved_test_run_id}.json",
                {
                    "report_schema_version": "1",
                    "test_run_id": resolved_test_run_id,
                    "scenario_id": scenario.name,
                    "cycles": iterations,
                    "status": status,
                    "is_test_data": True,
                    "devices": [snapshot],
                },
            )

    persist("running")
    print(f"test_run_id={resolved_test_run_id} manifest_saved=true")
    try:
        with DeviceApiClient(config) as client:
            while iterations is None or completed < iterations:
                actions = scenario.next_actions(config, datetime.now(timezone.utc))
                if actions:
                    network_latency = float(getattr(scenario, "network_latency_seconds", 0))
                    if network_latency > 0:
                        time.sleep(network_latency)
                    result = client.send_batch_with_retry(
                        actions,
                        test_run_id=resolved_test_run_id,
                    )
                    for record in result["records"]:
                        record_ids.append(record["id"])
                        print(
                            f"scenario={scenario.name} action={record['type']} "
                            f"record_id={record['id']} accepted"
                        )
                else:
                    print(
                        f"scenario={scenario.name} no_upload=true "
                        "heartbeat remains suspended for offline simulation"
                    )
                completed += 1
                persist("running")
                if iterations is None or completed < iterations:
                    time.sleep(config.interval_seconds)
    except BaseException:
        persist("interrupted")
        raise
    persist("completed")
    return {
        "test_run_id": resolved_test_run_id,
        "scenario": scenario.name,
        "cycles": completed,
        "record_ids": record_ids,
    }
