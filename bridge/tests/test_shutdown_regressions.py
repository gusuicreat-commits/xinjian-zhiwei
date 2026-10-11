import threading

from xinjian_serial_bridge.batcher import PendingBatch
from xinjian_serial_bridge.runtime import BatchDispatcher
from xinjian_serial_bridge.transport import SendOutcome


def test_shutdown_retryable_failure_is_unsent_not_discarded():
    class OfflineSender:
        def send(self, batch):
            return SendOutcome("retryable", 1, 503)

    dispatcher = BatchDispatcher(OfflineSender(), report=lambda _: None)
    dispatcher.submit(PendingBatch({"requestId": "one", "records": []}))
    dispatcher.start()
    assert dispatcher.finish(timeout=1) == (0, 1, 0)


def test_shutdown_timeout_never_sends_the_next_batch():
    entered = threading.Event()
    release = threading.Event()
    completed = threading.Event()
    calls = []

    class BlockedSender:
        def send(self, batch):
            calls.append(batch.payload["requestId"])
            entered.set()
            assert release.wait(2)
            completed.set()
            return SendOutcome("accepted", 1, 200)

    dispatcher = BatchDispatcher(BlockedSender(), report=lambda _: None)
    dispatcher.submit(PendingBatch({"requestId": "one", "records": []}))
    dispatcher.submit(PendingBatch({"requestId": "two", "records": []}))
    dispatcher.start()
    assert entered.wait(1)
    assert dispatcher.finish(timeout=0.01) == (0, 2, 0)
    release.set()
    assert completed.wait(1)
    dispatcher._thread.join(1)
    assert calls == ["one"]
