"""HTTP transport with bounded retries and response-contract validation."""

from __future__ import annotations

import time
from dataclasses import dataclass
from threading import Event
from typing import Callable, Optional

import httpx

from .batcher import PendingBatch


@dataclass(frozen=True)
class SendOutcome:
    """Classified result used by the asynchronous dispatcher."""

    status: str
    attempts: int
    http_status: Optional[int] = None

    def __bool__(self) -> bool:
        return self.status == "accepted"

    @property
    def retryable(self) -> bool:
        return self.status == "retryable"

    @property
    def authentication_error(self) -> bool:
        return self.status == "auth_error"


class Sender:
    def __init__(
        self,
        *,
        base_url: str,
        device_id: str,
        token: str,
        session_id: Optional[str] = None,
        max_attempts: int = 3,
        backoff_seconds: float = 0.5,
        client: Optional[httpx.Client] = None,
        sleep: Optional[Callable[[float], None]] = None,
        report: Callable[[str], None] = print,
    ) -> None:
        self.url = base_url.rstrip("/") + "/api/v1/device/ingest"
        self.headers = {"X-Device-ID": device_id, "X-Device-Token": token}
        if session_id:
            self.headers["X-Experiment-Session-ID"] = session_id
        self.max_attempts = max_attempts
        self.backoff_seconds = backoff_seconds
        self.client = client or httpx.Client(timeout=10.0)
        self._owns_client = client is None
        self.sleep = sleep
        self.report = report
        self._cancelled = Event()
        self._shutdown = Event()
        self._shutdown_deadline: Optional[float] = None

    def begin_shutdown(self, deadline: float) -> None:
        self._shutdown_deadline = deadline
        self._shutdown.set()

    def cancel(self) -> None:
        self._cancelled.set()
        self._shutdown.set()

    def _pause(self, delay: float) -> None:
        if self._shutdown_deadline is not None:
            return
        if self.sleep is not None:
            self.sleep(delay)
        else:
            self._shutdown.wait(delay)

    def close(self) -> None:
        if self._owns_client:
            self.client.close()

    def send(self, batch: PendingBatch) -> SendOutcome:
        request_id = batch.payload["requestId"]
        for attempt in range(1, self.max_attempts + 1):
            deadline = self._shutdown_deadline
            if self._cancelled.is_set() or (
                deadline is not None and (time.monotonic() >= deadline or attempt > 1)
            ):
                return SendOutcome("retryable", attempt - 1)
            try:
                timeout = 10.0 if deadline is None else min(10.0, deadline - time.monotonic())
                response = self.client.post(
                    self.url, headers=self.headers, json=batch.payload, timeout=max(0.001, timeout)
                )
            except httpx.HTTPError:
                if attempt == self.max_attempts:
                    self.report(
                        f"batch {request_id} failed: transport error after {attempt} attempts"
                    )
                    return SendOutcome("retryable", attempt)
                self._pause(self.backoff_seconds * (2 ** (attempt - 1)))
                continue
            if response.status_code in (200, 201):
                if self._valid_receipt(response, batch):
                    return SendOutcome("accepted", attempt, response.status_code)
                self.report(f"batch {request_id} failed: invalid server receipt")
                return SendOutcome("discarded", attempt, response.status_code)
            if response.status_code in (401, 403):
                self.report(
                    f"batch {request_id} rejected with HTTP {response.status_code}; "
                    "check device credentials"
                )
                return SendOutcome("auth_error", attempt, response.status_code)
            retryable = response.status_code in (408, 429) or 500 <= response.status_code < 600
            if not retryable or attempt == self.max_attempts:
                self.report(f"batch {request_id} rejected with HTTP {response.status_code}")
                return SendOutcome(
                    "retryable" if retryable else "discarded",
                    attempt,
                    response.status_code,
                )
            self._pause(self.backoff_seconds * (2 ** (attempt - 1)))
        return SendOutcome("retryable", self.max_attempts)

    @staticmethod
    def _valid_receipt(response: httpx.Response, batch: PendingBatch) -> bool:
        try:
            body = response.json()
        except ValueError:
            return False
        return (
            isinstance(body, dict)
            and body.get("requestId") == batch.payload["requestId"]
            and isinstance(body.get("records"), list)
            and len(body["records"]) == len(batch.payload["records"])
        )
