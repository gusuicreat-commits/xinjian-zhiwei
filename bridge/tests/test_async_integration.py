"""Concurrency regressions through real Sender + MockTransport, without hardware."""

import json
import threading
from argparse import Namespace

import httpx
import pytest

from xinjian_serial_bridge import cli
from xinjian_serial_bridge.batcher import BatchBuilder, PendingBatch
from xinjian_serial_bridge.runtime import BatchDispatcher, process_lines
from xinjian_serial_bridge.transport import Sender


def batch(number):
    return PendingBatch({"requestId": str(number), "sequenceNo": number, "records": [{}]})


def accepted(request):
    payload = json.loads(request.content)
    return httpx.Response(
        200,
        json={
            "requestId": payload["requestId"],
            "records": [{"status": "accepted"} for _ in payload["records"]],
        },
    )


def sender(handler, reports):
    return Sender(
        base_url="http://example.test",
        device_id="device",
        token="private-test-token",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        max_attempts=1,
        report=reports.append,
    )


def test_live_reads_echoes_and_batches_while_http_is_blocked(capsys, monkeypatch):
    entered, release, consumed = threading.Event(), threading.Event(), threading.Event()
    calls, reports = [], []

    def handler(request):
        calls.append(json.loads(request.content))
        if len(calls) == 1:
            entered.set()
            assert release.wait(2), "serial loop stopped reading while HTTP was blocked"
            return httpx.Response(503)
        return accepted(request)

    class SerialStream:
        index = 0
        closed = False

        def read(self, size):
            self.index += 1
            if self.index == 1:
                return b"SHT31 \xe4\xbc\xa0\xe6\x84\x9f\xe5\x99\xa8\xe5\x90\xaf\xe5\x8a\xa8!\r\n"
            if self.index == 2:
                assert entered.wait(1)
                return "温度: -3.25 ℃ | 湿度: 42.06 %RH\n".encode()
            if self.index == 3:
                consumed.set()
                release.set()
                raise KeyboardInterrupt

        def close(self):
            self.closed = True

    stream = SerialStream()
    monkeypatch.setattr(cli, "_open_serial", lambda *_: stream)
    args = Namespace(dry_run=False, port="fake", baud=115200, reconnect=False, max_queued_batches=5)
    assert (
        cli._run_live(
            args, BatchBuilder(max_records=3, interval_seconds=0), sender(handler, reports)
        )
        == 0
    )
    assert consumed.is_set() and stream.closed
    assert calls[0] == calls[1]  # Retry preserves the complete batch, including requestId.
    assert [p["sequenceNo"] for p in calls] == [0, 0, 1]
    captured = capsys.readouterr()
    assert "SHT31 传感器启动!\r\n" in captured.out
    assert "温度: -3.25 ℃ | 湿度: 42.06 %RH\n" in captured.out
    assert "sent=2, unsent=0, discarded=0" in captured.err


def test_mock_422_does_not_block_next_batch_and_reports_discard():
    calls, reports = [], []
    done = threading.Event()

    def handler(request):
        calls.append(json.loads(request.content)["requestId"])
        if len(calls) == 1:
            return httpx.Response(422, text="private-test-token: full response must stay private")
        done.set()
        return accepted(request)

    dispatcher = BatchDispatcher(sender(handler, reports), report=reports.append)
    dispatcher.submit(batch(0))
    dispatcher.submit(batch(1))
    dispatcher.start()
    assert done.wait(1)
    assert dispatcher.finish(1) == (1, 0, 1)
    dispatcher.report_summary(unsent=0)
    assert calls == ["0", "1"]
    assert any("sent=1, unsent=0, discarded=1" in msg for msg in reports)
    assert "private-test-token" not in " ".join(reports)


def test_overflow_during_inflight_retry_keeps_generation_order():
    entered, release, done = threading.Event(), threading.Event(), threading.Event()
    calls, reports = [], []

    def handler(request):
        calls.append(json.loads(request.content)["requestId"])
        if len(calls) == 1:
            entered.set()
            assert release.wait(1)
            return httpx.Response(503)
        if len(calls) == 3:
            done.set()
        return accepted(request)

    dispatcher = BatchDispatcher(
        sender(handler, reports), max_batches=1, retry_wait_seconds=0, report=reports.append
    )
    dispatcher.start()
    dispatcher.submit(batch(0))
    assert entered.wait(1)
    dispatcher.submit(batch(1))
    dispatcher.submit(batch(2))
    release.set()
    assert done.wait(1)
    assert dispatcher.finish(1) == (2, 0, 1)
    assert calls == ["0", "0", "2"]
    assert any("queue full; discarded 1 batch" in msg for msg in reports)


@pytest.mark.parametrize("status", [401, 403])
def test_live_auth_rejection_stops_reading_and_returns_nonzero(status, capsys, monkeypatch):
    calls, reports = [], []
    replied = threading.Event()

    def handler(request):
        calls.append(request)
        return httpx.Response(status, text="private-test-token")

    # report occurs after dispatcher sets auth_error, so the next read can return.
    real_report = cli.BatchDispatcher.report_summary

    class Stream:
        reads = 0

        def read(self, size):
            self.reads += 1
            if self.reads == 1:
                return b"SHT31 \xe4\xbc\xa0\xe6\x84\x9f\xe5\x99\xa8\xe5\x90\xaf\xe5\x8a\xa8!\n"
            assert replied.wait(1)
            return b""

        def close(self):
            pass

    class ObservedDispatcher(BatchDispatcher):
        def __init__(self, *args, **kwargs):
            report = kwargs["report"]

            def observe(message):
                report(message)
                if "stopped after an authentication failure" in message:
                    replied.set()

            kwargs["report"] = observe
            super().__init__(*args, **kwargs)

        report_summary = real_report

    stream = Stream()
    monkeypatch.setattr(cli, "BatchDispatcher", ObservedDispatcher)
    monkeypatch.setattr(cli, "_open_serial", lambda *_: stream)
    args = Namespace(dry_run=False, port="fake", baud=115200, reconnect=False, max_queued_batches=5)
    assert cli._run_live(args, BatchBuilder(max_records=2), sender(handler, reports)) == 2
    assert len(calls) == 1 and stream.reads <= 2
    captured = capsys.readouterr()
    assert "sent=0, unsent=1, discarded=0" in captured.err
    assert "private-test-token" not in captured.err


def test_replay_stops_before_consuming_next_line_on_auth_error():
    consumed, reports = [], []
    ready = threading.Event()
    dispatcher = BatchDispatcher(
        sender(lambda _: httpx.Response(401), reports),
        report=lambda msg: ready.set() if "authentication failure" in msg else None,
    )
    dispatcher.start()

    def lines():
        consumed.append(1)
        yield "SHT31 传感器启动!\n"
        consumed.append(2)
        yield "温度: 26.56 ℃ | 湿度: 40.80 %RH\n"

    def emit(payload):
        dispatcher.submit(payload)
        assert ready.wait(1)
        return True

    process_lines(
        lines(),
        builder=BatchBuilder(max_records=2, replay=True),
        emit_batch=emit,
        should_stop=lambda: dispatcher.auth_error,
    )
    assert consumed == [1]
    assert dispatcher.finish(1) == (0, 1, 0)
