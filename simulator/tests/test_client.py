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


def test_client_builds_protocol_v1_batch() -> None:
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        body = request.read()
        assert b'"protocolVersion":"1.0"' in body
        assert b'"schemaVersion":"1"' in body
        assert b'"isTestData":true' in body
        assert b'"occurredAt":"2026-07-27T00:00:00Z"' in body
        assert b'"observed_at"' not in body
        return httpx.Response(
            201,
            json={
                "requestId": "protocol-request",
                "deviceId": "test-device",
                "acceptedAt": "2026-07-27T00:00:01Z",
                "idempotentReplay": False,
                "retryable": False,
                "records": [
                    {
                        "index": 0,
                        "type": "heartbeat",
                        "id": "heartbeat-record",
                        "status": "accepted",
                        "timeQuality": "device_reported",
                    }
                ],
            },
        )

    config = SimulationConfig(
        api_base_url="http://testserver",
        device_id="test-device",
        device_token="test-token",
    )
    action = UploadAction(
        kind="heartbeat",
        payload={"observed_at": "2026-07-27T00:00:00Z", "is_test_data": True},
    )

    with DeviceApiClient(config, transport=httpx.MockTransport(handler)) as client:
        result = client.send_batch([action], request_id="protocol-request")

    assert result["records"][0]["id"] == "heartbeat-record"
    assert captured[0].url.path == "/api/v1/device/ingest"


def test_retry_reuses_same_request_and_applies_exponential_backoff() -> None:
    request_bodies: list[bytes] = []
    delays: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        request_bodies.append(request.read())
        if len(request_bodies) < 3:
            return httpx.Response(503, json={"detail": {"retryable": True}})
        return httpx.Response(
            201,
            json={
                "requestId": "eventual-success",
                "deviceId": "test-device",
                "acceptedAt": "2026-07-27T00:00:01Z",
                "idempotentReplay": False,
                "retryable": False,
                "records": [],
            },
        )

    config = SimulationConfig(
        api_base_url="http://testserver",
        device_id="test-device",
        device_token="test-token",
        retry_max_attempts=3,
        retry_base_delay_seconds=0.5,
    )
    action = UploadAction(
        kind="heartbeat",
        payload={"observed_at": "2026-07-27T00:00:00Z", "is_test_data": True},
    )

    with DeviceApiClient(config, transport=httpx.MockTransport(handler)) as client:
        client.send_batch_with_retry([action], sleep=delays.append)

    assert request_bodies[0] == request_bodies[1] == request_bodies[2]
    assert delays == [0.5, 1.0]
