"""Bounded record batching and boot/heartbeat state."""

from __future__ import annotations

import json
import time
from collections import deque
from dataclasses import dataclass
from datetime import datetime
from threading import Condition
from typing import Callable, Optional
from uuid import uuid4

from .parser import ParsedLine
from .protocol import FIRMWARE_VERSION, heartbeat_record, make_batch, record_for_line


@dataclass
class PendingBatch:
    payload: dict


class BatchBuilder:
    def __init__(
        self,
        *,
        max_records: int = 50,
        interval_seconds: float = 5.0,
        firmware_version: str = FIRMWARE_VERSION,
        is_test_data: bool = True,
        replay: bool = False,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if max_records < 2 or max_records > 100:
            raise ValueError("max_records must be between 2 and 100")
        if not firmware_version or len(firmware_version) > 100:
            raise ValueError("firmware_version must contain 1..100 characters")
        if interval_seconds < 0:
            raise ValueError("interval_seconds must be nonnegative")
        self.max_records = max_records
        self.interval_seconds = interval_seconds
        self.firmware_version = firmware_version
        self.is_test_data = is_test_data
        self.replay = replay
        self.clock = clock
        self.boot_id = str(uuid4())
        self.sequence_no = 0
        self.records: list[dict] = []
        self.activity_since_heartbeat = False
        self.last_activity_at: Optional[datetime] = None
        self.last_flush_monotonic = clock()

    def add(self, parsed: ParsedLine, *, received_at: Optional[datetime]) -> list[PendingBatch]:
        batches: list[PendingBatch] = []
        if parsed.kind == "boot":
            if self.records:
                batch = self.flush(force=True)
                if batch:
                    batches.append(batch)
            self.boot_id = str(uuid4())
            self.sequence_no = 0
        line_records = record_for_line(parsed, received_at=received_at, replay=self.replay)
        self.activity_since_heartbeat = True
        self.last_activity_at = received_at
        for record in line_records:
            if len(self.records) >= self.max_records - 1:
                batch = self.flush(force=True)
                if batch:
                    batches.append(batch)
            self.records.append(record)
        if len(self.records) >= self.max_records - 1:
            batch = self.flush(force=True)
            if batch:
                batches.append(batch)
        return batches

    def should_flush(self) -> bool:
        return bool(self.records) and (
            self.clock() - self.last_flush_monotonic >= self.interval_seconds
        )

    def flush(self, *, force: bool = False) -> Optional[PendingBatch]:
        if not self.records:
            return None
        if not force and not self.should_flush():
            return None
        records = self.records
        self.records = []
        if self.activity_since_heartbeat and len(records) < self.max_records:
            records.append(heartbeat_record(received_at=self.last_activity_at, replay=self.replay))
            self.activity_since_heartbeat = False
        payload = make_batch(
            records,
            boot_id=self.boot_id,
            sequence_no=self.sequence_no,
            firmware_version=self.firmware_version,
            is_test_data=self.is_test_data,
        )
        if self.encoded_size(PendingBatch(payload)) > 262144:
            raise ValueError("batch exceeds the backend 262144-byte body limit")
        self.sequence_no += 1
        self.last_flush_monotonic = self.clock()
        return PendingBatch(payload)

    def encoded_size(self, batch: PendingBatch) -> int:
        return len(json.dumps(batch.payload, ensure_ascii=False, separators=(",", ":")).encode())


class BoundedBatchQueue:
    def __init__(self, max_batches: int = 20, *, report: Callable[[str], None] = print) -> None:
        if max_batches < 1:
            raise ValueError("max_batches must be positive")
        self._items: deque[PendingBatch] = deque()
        self._condition = Condition()
        self.max_batches = max_batches
        self.report = report
        self.discarded_batches = 0

    def put(self, batch: PendingBatch) -> None:
        with self._condition:
            if len(self._items) >= self.max_batches:
                self._items.popleft()
                self.discarded_batches += 1
                self.report(
                    f"serial bridge queue full; discarded 1 batch (total={self.discarded_batches})"
                )
            self._items.append(batch)
            self._condition.notify()

    def get(self) -> Optional[PendingBatch]:
        with self._condition:
            return self._items.popleft() if self._items else None

    def __len__(self) -> int:
        with self._condition:
            return len(self._items)
