"""Bounded transport and retry classification, without any external provider."""

import asyncio
import gzip
import json
import time

import httpx
import pytest

from app.ai.clients import AIProviderError, OpenAICompatibleClient, retry_after_seconds


class BytesStream(httpx.AsyncByteStream):
    def __init__(self, data=b"", delay=0, count=1):
        self.data, self.delay, self.count = data, delay, count
        self.closed = False

    async def __aiter__(self):
        for _ in range(self.count):
            await asyncio.sleep(self.delay)
            yield self.data

    async def aclose(self):
        self.closed = True


def client_transport(monkeypatch, stream, *, status=200, headers=None, timeout=0.1, cap=1024):
    async def handle(request):
        return httpx.Response(status, headers=headers or {}, stream=stream)

    factory = httpx.AsyncClient
    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kwargs: factory(transport=httpx.MockTransport(handle), **kwargs),
    )
    return OpenAICompatibleClient(
        provider="synthetic",
        model="synthetic",
        base_url="http://local.invalid",
        api_key="synthetic",
        timeout_seconds=timeout,
        max_retries=3,
        response_max_bytes=cap,
    )


def test_drip_response_hits_total_deadline_and_closes(monkeypatch):
    stream = BytesStream(b" ", delay=0.01, count=1000)
    client = client_transport(monkeypatch, stream)
    began = time.monotonic()
    with pytest.raises(AIProviderError) as error:
        client.complete_json_once(system_prompt="test", user_prompt="test")
    assert error.value.outcome_unknown
    assert not error.value.retryable
    assert time.monotonic() - began < 0.5
    assert stream.closed


@pytest.mark.parametrize("compressed", [False, True])
def test_wire_and_expanded_body_have_bounds(monkeypatch, compressed):
    raw = json.dumps({"text": "x" * 100000}).encode()
    stream = BytesStream(gzip.compress(raw) if compressed else raw)
    client = client_transport(
        monkeypatch, stream, headers={"content-encoding": "gzip"} if compressed else {}
    )
    with pytest.raises(AIProviderError) as error:
        client.complete_json_once(system_prompt="test", user_prompt="test")
    assert error.value.code == "RESPONSE_LIMIT"
    assert stream.closed


@pytest.mark.parametrize(
    "status,retryable,unknown",
    [
        (400, False, False),
        (401, False, False),
        (403, False, False),
        (429, True, False),
        (500, False, True),
        (503, False, True),
    ],
)
def test_http_status_preserves_safe_retry_information(monkeypatch, status, retryable, unknown):
    stream = BytesStream(b"synthetic-secret-not-to-log")
    client = client_transport(monkeypatch, stream, status=status, headers={"retry-after": "3"})
    with pytest.raises(AIProviderError) as error:
        client.complete_json_once(system_prompt="test", user_prompt="test")
    assert error.value.status_code == status
    assert error.value.retryable is retryable
    assert error.value.outcome_unknown is unknown
    assert "secret" not in str(error.value)
    assert stream.closed


def test_retry_after_date_and_invalid_values():
    from datetime import datetime, timedelta, timezone
    from email.utils import format_datetime

    value = format_datetime(datetime.now(timezone.utc) + timedelta(seconds=10))
    assert 8 <= retry_after_seconds(value) <= 10
    assert retry_after_seconds("nan") is None
    assert retry_after_seconds("-1") is None
    assert retry_after_seconds("bad") is None
