import json

import httpx

from xinjian_serial_bridge.batcher import PendingBatch
from xinjian_serial_bridge.transport import Sender


def _batch():
    return PendingBatch({"requestId": "request-1", "records": [{"type": "log"}]})


def test_retry_reuses_same_request_id_and_accepts_201():
    seen = []

    def handler(request):
        seen.append(json.loads(request.content)["requestId"])
        if len(seen) == 1:
            return httpx.Response(503, request=request)
        return httpx.Response(
            201,
            json={"requestId": "request-1", "records": [{"status": "accepted"}]},
            request=request,
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    sender = Sender(
        base_url="http://example.test",
        device_id="device",
        token="secret",
        client=client,
        max_attempts=2,
        sleep=lambda _: None,
    )
    assert sender.send(_batch())
    assert seen == ["request-1", "request-1"]


def test_invalid_receipt_is_not_success():
    def handler(request):
        return httpx.Response(200, json={"requestId": "other", "records": []}, request=request)

    sender = Sender(
        base_url="http://example.test",
        device_id="device",
        token="secret",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        sleep=lambda _: None,
    )
    assert not sender.send(_batch())


def test_permanent_client_rejection_is_discarded_without_retry():
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(422, request=request)

    sender = Sender(
        base_url="http://example.test",
        device_id="device",
        token="secret",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        sleep=lambda _: None,
    )
    outcome = sender.send(_batch())
    assert not outcome
    assert outcome.status == "discarded"
    assert len(calls) == 1


def test_authentication_rejection_is_distinct_and_does_not_retry():
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(401, request=request)

    sender = Sender(
        base_url="http://example.test",
        device_id="device",
        token="secret",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        sleep=lambda _: None,
    )
    outcome = sender.send(_batch())
    assert not outcome
    assert outcome.authentication_error
    assert len(calls) == 1


def test_nonobject_json_receipt_is_rejected_without_exception():
    sender = Sender(
        base_url="http://example.test",
        device_id="device",
        token="secret",
        client=httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(200, json=[]))),
    )
    assert sender.send(_batch()).status == "discarded"


def test_shutdown_tries_a_batch_only_once_without_backoff():
    import time

    calls = []
    delays = []

    def handler(request):
        calls.append(request)
        return httpx.Response(503)

    sender = Sender(
        base_url="http://example.test",
        device_id="device",
        token="secret",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        sleep=delays.append,
    )
    sender.begin_shutdown(time.monotonic() + 1)
    assert sender.send(_batch()).retryable
    assert len(calls) == 1 and delays == []
    sender.cancel()
    assert sender.send(_batch()).retryable
    assert len(calls) == 1
