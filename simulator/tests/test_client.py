import httpx

from xinjian_simulator.actions import UploadAction
from xinjian_simulator.client import DeviceApiClient
from xinjian_simulator.config import SimulationConfig


def test_client_sends_credentials_and_test_payload_without_logging_token() -> None:
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(
            201,
            json={
                "id": "test-record",
                "device_id": "test-device",
                "accepted_at": "2026-07-19T00:00:00Z",
            },
        )

    config = SimulationConfig(
        api_base_url="http://testserver",
        device_id="test-device",
        device_token="test-token",
    )
    action = UploadAction(
        kind="heartbeat",
        payload={"observed_at": "2026-07-19T00:00:00Z", "is_test_data": True},
    )

    with DeviceApiClient(config, transport=httpx.MockTransport(handler)) as client:
        result = client.send(action)

    assert result["id"] == "test-record"
    assert captured[0].url.path == "/api/v1/device/heartbeat"
    assert captured[0].headers["X-Device-ID"] == "test-device"
    assert captured[0].headers["X-Device-Token"] == "test-token"
    assert b'"is_test_data":true' in captured[0].content
