import pytest

from xinjian_simulator.config import SimulationConfig


def test_required_device_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("XINJIAN_DEVICE_ID", raising=False)
    monkeypatch.delenv("XINJIAN_DEVICE_TOKEN", raising=False)

    with pytest.raises(ValueError, match="XINJIAN_DEVICE_ID is required"):
        SimulationConfig.from_env()


def test_token_is_not_exposed_by_config_repr(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("XINJIAN_DEVICE_ID", "test-device")
    monkeypatch.setenv("XINJIAN_DEVICE_TOKEN", "test-secret-token")

    config = SimulationConfig.from_env()

    assert "test-secret-token" not in repr(config)
    assert config.sensor_type == "generic-test-sensor"


@pytest.mark.parametrize(
    "field", ["interval_seconds", "request_timeout_seconds", "retry_base_delay_seconds"]
)
@pytest.mark.parametrize("value", [float("nan"), float("inf"), -float("inf"), 0, -1])
def test_invalid_timing_rejected_before_client_construction(field, value):
    with pytest.raises(ValueError):
        SimulationConfig(
            api_base_url="http://test.invalid",
            device_id="test",
            device_token="secret",
            **{field: value},
        )
