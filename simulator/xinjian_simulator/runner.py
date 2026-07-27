import time
from datetime import datetime, timezone
from typing import Optional
from uuid import uuid4

from xinjian_simulator.client import DeviceApiClient
from xinjian_simulator.config import SimulationConfig
from xinjian_simulator.scenarios import Scenario


def run_scenario(
    scenario: Scenario,
    config: SimulationConfig,
    iterations: Optional[int] = None,
    test_run_id: Optional[str] = None,
) -> dict[str, object]:
    completed = 0
    resolved_test_run_id = test_run_id or str(uuid4())
    record_ids: list[str] = []
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
            if iterations is None or completed < iterations:
                time.sleep(config.interval_seconds)
    return {
        "test_run_id": resolved_test_run_id,
        "scenario": scenario.name,
        "cycles": completed,
        "record_ids": record_ids,
    }
