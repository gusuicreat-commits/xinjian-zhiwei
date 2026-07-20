import time
from datetime import datetime, timezone
from typing import Optional

from xinjian_simulator.client import DeviceApiClient
from xinjian_simulator.config import SimulationConfig
from xinjian_simulator.scenarios import Scenario


def run_scenario(
    scenario: Scenario,
    config: SimulationConfig,
    iterations: Optional[int] = None,
) -> None:
    completed = 0
    with DeviceApiClient(config) as client:
        while iterations is None or completed < iterations:
            actions = scenario.next_actions(config, datetime.now(timezone.utc))
            if actions:
                for action in actions:
                    result = client.send(action)
                    print(
                        f"scenario={scenario.name} action={action.kind} "
                        f"record_id={result['id']} accepted"
                    )
            else:
                print(
                    f"scenario={scenario.name} no_upload=true "
                    "heartbeat remains suspended for offline simulation"
                )
            completed += 1
            if iterations is None or completed < iterations:
                time.sleep(config.interval_seconds)
