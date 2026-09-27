import json
from unittest.mock import MagicMock

import pytest

from xinjian_simulator.config import SimulationConfig
from xinjian_simulator.dsl import DslScenario, load_spec
from xinjian_simulator.runner import run_scenario


def test_interruption_keeps_identity_and_accepted_records(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    client = MagicMock()
    client.__enter__.return_value = client
    calls = 0

    def send(*args, **kwargs):
        nonlocal calls
        calls += 1
        manifest = json.loads(next((tmp_path / ".simulator-runs").glob("*.json")).read_text())
        assert manifest["test_run_id"] == kwargs["test_run_id"]
        if calls == 2:
            raise RuntimeError("synthetic transport interruption")
        return {"records": [{"id": "accepted-id", "type": "reading"}]}

    client.send_batch_with_retry.side_effect = send
    monkeypatch.setattr("xinjian_simulator.runner.DeviceApiClient", lambda config: client)
    monkeypatch.setattr("xinjian_simulator.runner.time.sleep", lambda seconds: None)
    config = SimulationConfig(
        api_base_url="http://test.invalid", device_id="synthetic", device_token="private-token"
    )
    with pytest.raises(RuntimeError):
        run_scenario(DslScenario(load_spec("normal")), config, 2)
    manifest = json.loads(next((tmp_path / ".simulator-runs").glob("*.json")).read_text())
    assert manifest["status"] == "interrupted"
    assert manifest["devices"][0]["record_ids"] == ["accepted-id"]
    assert "private-token" not in json.dumps(manifest)
