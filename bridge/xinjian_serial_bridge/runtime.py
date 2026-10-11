"""Serial/replay processing loops."""

from __future__ import annotations

import sys
import time
from collections.abc import Iterable
from datetime import datetime, timezone
from pathlib import Path
from threading import Condition, Event, Thread
from typing import Callable, Optional

from .batcher import BatchBuilder, BoundedBatchQueue, PendingBatch
from .parser import parse_line


def _receive_time() -> datetime:
    return datetime.now(timezone.utc)


def process_lines(
    lines: Iterable[str],
    *,
    builder: BatchBuilder,
    emit_batch: Callable[[PendingBatch], bool],
    dry_run: bool = False,
    echo: bool = False,
    stderr=None,
    should_stop: Callable[[], bool] = lambda: False,
) -> int:
    """Process replay or a finite fake stream and flush its final batch."""
    stderr = stderr or sys.stderr
    sent = 0
    unknown_count = 0
    iterator = iter(lines)
    while not should_stop():
        try:
            raw_line = next(iterator)
        except StopIteration:
            break
        if echo:
            print(raw_line.rstrip("\r\n"), flush=True)
        parsed = parse_line(raw_line)
        if parsed is None:
            unknown_count += 1
            print(f"unrecognized serial line: {raw_line.rstrip(chr(13) + chr(10))!r}", file=stderr)
            continue
        received_at = None if builder.replay else _receive_time()
        for batch in builder.add(parsed, received_at=received_at):
            if emit_batch(batch):
                sent += 1
    if not should_stop():
        batch = builder.flush(force=True)
        if batch and emit_batch(batch):
            sent += 1
    if unknown_count:
        print(f"unrecognized serial lines: {unknown_count}", file=stderr)
    return sent


def replay_file(
    path: Path,
    *,
    builder: BatchBuilder,
    emit_batch: Callable[[PendingBatch], bool],
    should_stop: Callable[[], bool] = lambda: False,
) -> int:
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        return process_lines(
            handle, builder=builder, emit_batch=emit_batch, should_stop=should_stop
        )


class BatchDispatcher:
    """One HTTP worker; retain the current batch until accepted or rejected."""

    def __init__(
        self,
        sender,
        *,
        max_batches: int = 20,
        report: Callable[[str], None] = print,
        retry_wait_seconds: float = 1.0,
    ) -> None:
        self.sender = sender
        self.report = report
        self.queue = BoundedBatchQueue(max_batches, report=report)
        self.retry_wait_seconds = retry_wait_seconds
        self._wake = Condition()
        self._finish_requested = Event()
        self._abort = Event()
        self._deadline: Optional[float] = None
        self._thread: Optional[Thread] = None
        self._current: Optional[PendingBatch] = None
        self._final_unsent = 0
        self._summary: Optional[tuple[int, int, int]] = None
        self.sent_batches = 0
        self.discarded_batches = 0
        self.auth_error = False

    def start(self) -> None:
        if self._thread is None:
            self._thread = Thread(target=self._worker, name="serial-bridge-sender", daemon=True)
            self._thread.start()

    def submit(self, batch: PendingBatch) -> None:
        with self._wake:
            if self._finish_requested.is_set():
                self.discarded_batches += 1
                self.report("serial bridge stopped; discarded 1 batch")
                return
            self.queue.put(batch)
            self._wake.notify()

    def _worker(self) -> None:
        try:
            self._send_loop()
        finally:
            # The worker owns the client: never close it under an in-flight request.
            close = getattr(self.sender, "close", None)
            if close is not None:
                close()

    def _send_loop(self) -> None:
        while True:
            with self._wake:
                if self._abort.is_set() or (
                    self._deadline is not None and time.monotonic() >= self._deadline
                ):
                    return
                if self._current is None:
                    self._current = self.queue.get()
                if self._current is None:
                    if self._finish_requested.is_set():
                        return
                    self._wake.wait(timeout=0.2)
                    continue
                batch = self._current
                final_attempt = self._finish_requested.is_set()
            outcome = self.sender.send(batch)
            with self._wake:
                if self._abort.is_set():
                    # A receipt after the shutdown deadline cannot change its summary.
                    return
                if outcome:
                    self.sent_batches += 1
                    self._current = None
                elif outcome.authentication_error:
                    self.auth_error = True
                    self.report("serial bridge stopped after an authentication failure")
                    return
                elif outcome.retryable:
                    if final_attempt:
                        self._final_unsent += 1
                        self._current = None
                    # Otherwise keep this batch in-flight, ahead of all newer batches.
                else:
                    self.discarded_batches += 1
                    self._current = None
                    self.report(
                        "serial bridge permanent rejection; discarded 1 batch "
                        f"(total={self.discarded_batches + self.queue.discarded_batches})"
                    )
            if outcome.retryable and not self._finish_requested.is_set():
                self._finish_requested.wait(self.retry_wait_seconds)

    def finish(self, timeout: float = 15.0) -> tuple[int, int, int]:
        """Try pending batches once within a shared deadline; freeze exit accounting."""
        with self._wake:
            self._deadline = time.monotonic() + max(0.0, timeout)
            begin_shutdown = getattr(self.sender, "begin_shutdown", None)
            if begin_shutdown is not None:
                begin_shutdown(self._deadline)
            self._finish_requested.set()
            self._wake.notify_all()
        if self._thread is not None:
            self._thread.join(timeout=max(0.0, self._deadline - time.monotonic()))
        with self._wake:
            self._abort.set()
            cancel = getattr(self.sender, "cancel", None)
            if cancel is not None:
                cancel()
            unsent = len(self.queue) + int(self._current is not None) + self._final_unsent
            self._summary = (
                self.sent_batches,
                unsent,
                self.discarded_batches + self.queue.discarded_batches,
            )
            if self._thread is not None and self._thread.is_alive():
                self.report(f"serial bridge final send timed out with {unsent} batch(es) pending")
            return self._summary

    def report_summary(self, *, unsent: int) -> None:
        sent, unsent, discarded = self._summary or (
            self.sent_batches,
            unsent,
            self.discarded_batches + self.queue.discarded_batches,
        )
        self.report(f"serial bridge shutdown: sent={sent}, unsent={unsent}, discarded={discarded}")
