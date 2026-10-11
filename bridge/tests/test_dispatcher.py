import threading

from xinjian_serial_bridge.batcher import PendingBatch
from xinjian_serial_bridge.runtime import BatchDispatcher
from xinjian_serial_bridge.transport import SendOutcome


def _batch(request_id: str) -> PendingBatch:
    return PendingBatch({"requestId": request_id, "records": []})


class SequenceSender:
    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.calls = []
        self.done = threading.Event()

    def send(self, batch):
        self.calls.append(batch.payload["requestId"])
        outcome = self.outcomes.pop(0)
        if not self.outcomes:
            self.done.set()
        return outcome


def test_retryable_batch_stays_ahead_of_newer_batches():
    sender = SequenceSender(
        [
            SendOutcome("retryable", 3, 503),
            SendOutcome("accepted", 1, 200),
            SendOutcome("accepted", 1, 200),
        ]
    )
    dispatcher = BatchDispatcher(sender, max_batches=5, retry_wait_seconds=0)
    dispatcher.start()
    dispatcher.submit(_batch("first"))
    dispatcher.submit(_batch("second"))
    assert sender.done.wait(2)
    _, unsent, _ = dispatcher.finish(timeout=2)
    assert unsent == 0
    assert sender.calls == ["first", "first", "second"]


def test_dispatcher_submit_does_not_wait_for_blocked_http_sender():
    entered = threading.Event()
    release = threading.Event()

    class BlockedSender:
        def send(self, batch):
            entered.set()
            release.wait(2)
            return SendOutcome("accepted", 1, 200)

    dispatcher = BatchDispatcher(BlockedSender(), max_batches=5)
    dispatcher.start()
    dispatcher.submit(_batch("first"))
    assert entered.wait(1)
    dispatcher.submit(_batch("second"))
    assert len(dispatcher.queue) == 1
    release.set()
    _, unsent, _ = dispatcher.finish(timeout=2)
    assert unsent == 0


def test_final_drain_reports_permanent_discard_and_summary():
    reports = []
    sender = SequenceSender([SendOutcome("discarded", 1, 422), SendOutcome("discarded", 1, 422)])
    dispatcher = BatchDispatcher(sender, max_batches=5, report=reports.append)
    dispatcher.start()
    dispatcher.submit(_batch("one"))
    dispatcher.submit(_batch("two"))
    assert sender.done.wait(1)
    _, unsent, discarded = dispatcher.finish(timeout=2)
    dispatcher.report_summary(unsent=unsent)
    assert unsent == 0
    assert discarded == 2
    assert any("sent=0, unsent=0, discarded=2" in message for message in reports)
