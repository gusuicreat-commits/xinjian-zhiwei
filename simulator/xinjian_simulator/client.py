from typing import Any, Optional

import httpx

from xinjian_simulator.actions import UploadAction
from xinjian_simulator.config import SimulationConfig

ACTION_PATHS = {
    "log": "/api/v1/device/logs",
    "reading": "/api/v1/device/readings",
    "heartbeat": "/api/v1/device/heartbeat",
}


class DeviceApiClient:
    def __init__(
        self,
        config: SimulationConfig,
        transport: Optional[httpx.BaseTransport] = None,
    ) -> None:
        self._device_id = config.device_id
        self._client = httpx.Client(
            base_url=config.api_base_url,
            timeout=config.request_timeout_seconds,
            headers={
                "X-Device-ID": config.device_id,
                "X-Device-Token": config.device_token,
            },
            transport=transport,
        )

    def __enter__(self) -> "DeviceApiClient":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def close(self) -> None:
        self._client.close()

    def send(self, action: UploadAction) -> dict[str, Any]:
        response = self._client.post(ACTION_PATHS[action.kind], json=action.payload)
        response.raise_for_status()
        return response.json()

    def get_status(self) -> dict[str, Any]:
        response = self._client.get(f"/api/v1/device/{self._device_id}/status")
        response.raise_for_status()
        return response.json()
