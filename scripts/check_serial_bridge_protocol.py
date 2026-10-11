#!/usr/bin/env python3
"""Validate the checked-in serial bridge protocol example against backend V1."""

from __future__ import annotations

import io
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "bridge"))

from app.core.config import Settings
from app.schemas.device import DeviceBatchIngestRequest
from app.services.device_protocol import _normalize_protocol_record
from xinjian_serial_bridge.batcher import BatchBuilder
from xinjian_serial_bridge.runtime import process_lines


def validate(payload: dict) -> int:
    parsed = DeviceBatchIngestRequest.model_validate(payload)
    defaults = Settings.model_fields
    if parsed.protocol_version != defaults["device_protocol_version"].default:
        raise SystemExit("bridge example protocolVersion is unsupported")
    if parsed.schema_version != defaults["device_schema_version"].default:
        raise SystemExit("bridge example schemaVersion is unsupported")
    if not parsed.is_test_data:
        raise SystemExit("bridge example must keep isTestData=true")
    if not parsed.records:
        raise SystemExit("bridge example must contain at least one record")
    encoded = json.dumps(
        parsed.model_dump(mode="json", by_alias=True),
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    if len(encoded) > defaults["device_ingest_max_body_bytes"].default:
        raise SystemExit("bridge example exceeds backend body limit")
    if len(parsed.records) > defaults["device_ingest_max_records"].default:
        raise SystemExit("bridge example exceeds backend record limit")
    for record in parsed.records:
        _normalize_protocol_record(
            record_type=record.type,
            occurred_at_raw=record.occurred_at,
            raw_payload=record.payload,
            is_test_data=parsed.is_test_data,
            firmware_version=parsed.firmware_version,
            server_received_at=datetime.now(timezone.utc),  # noqa: UP017 (Python 3.10 support)
        )
    return len(parsed.records)


def main() -> None:
    path = ROOT / "bridge/docs/protocol-example.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    count = validate(payload)
    generated = []
    with (ROOT / "bridge/docs/protocol-input.txt").open(encoding="utf-8") as lines:
        process_lines(
            lines,
            builder=BatchBuilder(replay=True),
            emit_batch=lambda batch: generated.append(batch.payload) or True,
            stderr=io.StringIO(),
        )
    if len(generated) != 1:
        raise SystemExit("fixed bridge input must produce one batch")
    validate(generated[0])

    def stable(batch: dict) -> dict:
        return {
            key: value
            for key, value in batch.items()
            if key not in {"requestId", "bootId"}
        }

    if stable(payload) != stable(generated[0]):
        raise SystemExit("bridge protocol example differs from current bridge output")
    print(
        f"serial bridge protocol consistency passed: example and generated records={count}"
    )


if __name__ == "__main__":
    main()
