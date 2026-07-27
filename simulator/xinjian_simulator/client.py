import time
from collections.abc import Sequence
from datetime import datetime, timezone
from typing import Any, Callable, Optional
from uuid import uuid4

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
        self._config = config
        self._boot_id = f"simulator-{uuid4()}"
        self._sequence_no = 0
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

    def build_batch(
        self,
        actions: Sequence[UploadAction],
        *,
        request_id: Optional[str] = None,
        sequence_no: Optional[int] = None,
        test_run_id: Optional[str] = None,
    ) -> dict[str, Any]:
        resolved_sequence = self._sequence_no if sequence_no is None else sequence_no
        records = []
        for action in actions:
            payload = dict(action.payload)
            occurred_at = payload.pop("occurred_at", None) or payload.pop("observed_at", None)
            payload.pop("is_test_data", None)
            records.append(
                {
                    "type": action.kind,
                    "occurredAt": occurred_at,
                    "payload": payload,
                }
            )
        return {
            "protocolVersion": self._config.protocol_version,
            "schemaVersion": self._config.schema_version,
            "requestId": request_id or str(uuid4()),
            "testRunId": test_run_id,
            "bootId": self._boot_id,
            "sequenceNo": resolved_sequence,
            "sentAt": datetime.now(timezone.utc).isoformat(),
            "uptimeMs": None,
            "firmwareVersion": self._config.firmware_version,
            "isTestData": True,
            "records": records,
        }

    def send_batch(
        self,
        actions: Sequence[UploadAction],
        *,
        request_id: Optional[str] = None,
    ) -> dict[str, Any]:
        batch = self.build_batch(actions, request_id=request_id)
        response = self._client.post("/api/v1/device/ingest", json=batch)
        response.raise_for_status()
        self._sequence_no += 1
        return response.json()

    def send_batch_with_retry(
        self,
        actions: Sequence[UploadAction],
        *,
        test_run_id: Optional[str] = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> dict[str, Any]:
        batch = self.build_batch(actions, test_run_id=test_run_id)
        for attempt in range(self._config.retry_max_attempts):
            try:
                response = self._client.post("/api/v1/device/ingest", json=batch)
            except (httpx.TimeoutException, httpx.TransportError):
                if attempt + 1 >= self._config.retry_max_attempts:
                    raise
                sleep(self._config.retry_base_delay_seconds * (2**attempt))
                continue
            retryable_status = (
                response.status_code in {408, 425, 429} or response.status_code >= 500
            )
            if retryable_status:
                if attempt + 1 >= self._config.retry_max_attempts:
                    response.raise_for_status()
                sleep(self._config.retry_base_delay_seconds * (2**attempt))
                continue
            response.raise_for_status()
            self._sequence_no += 1
            return response.json()
        raise RuntimeError("unreachable retry state")

    def cleanup_test_run(self, test_run_id: str) -> dict[str, Any]:
        response = self._client.delete(f"/api/v1/device/test-runs/{test_run_id}")
        response.raise_for_status()
        return response.json()

    def get_status(self) -> dict[str, Any]:
        response = self._client.get(f"/api/v1/device/{self._device_id}/status")
        response.raise_for_status()
        return response.json()
