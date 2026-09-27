#!/usr/bin/env python3
"""Check that the checked-in firmware protocol sample matches server contracts."""

from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BACKEND = ROOT / "backend"
FIRMWARE = ROOT / "firmware/esp32_dht11"
sys.path.insert(0, str(BACKEND))

from app.core.config import Settings  # noqa: E402
from app.schemas.device import DeviceBatchIngestRequest  # noqa: E402
from app.services.device_protocol import _normalize_protocol_record  # noqa: E402


def _match(pattern: str, text: str, *, source: Path) -> str:
    match = re.search(pattern, text, flags=re.MULTILINE)
    if not match:
        raise SystemExit(f"firmware version missing in {source}")
    return match.group(1)


def main() -> None:
    ini = (FIRMWARE / "platformio.ini").read_text(encoding="utf-8")
    config = (FIRMWARE / "include/firmware_config.h").read_text(encoding="utf-8")
    example_path = FIRMWARE / "docs/protocol-example.json"
    payload = json.loads(example_path.read_text(encoding="utf-8"))

    compiled_version = _match(
        r'-DXJ_FIRMWARE_VERSION=\\"([^\"]+)\\"',
        ini,
        source=FIRMWARE / "platformio.ini",
    )
    default_version = _match(
        r'^#define\s+XJ_FIRMWARE_VERSION\s+"([^"]+)"',
        config,
        source=FIRMWARE / "include/firmware_config.h",
    )
    example_version = payload.get("firmwareVersion")
    if compiled_version != default_version or example_version != compiled_version:
        raise SystemExit(
            "firmware version mismatch: "
            f"platformio={compiled_version!r}, default={default_version!r}, "
            f"protocol_example={example_version!r}"
        )

    parsed = DeviceBatchIngestRequest.model_validate(payload)
    defaults = Settings.model_fields
    if (
        parsed.protocol_version != defaults["device_protocol_version"].default
        or parsed.schema_version != defaults["device_schema_version"].default
    ):
        raise SystemExit(
            "firmware protocol example uses an unsupported protocol/schema version"
        )
    if len(parsed.records) > defaults["device_ingest_max_records"].default:
        raise SystemExit("firmware example exceeds the default record limit")
    encoded_size = len(
        json.dumps(
            parsed.model_dump(mode="json", by_alias=True),
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
    )
    if encoded_size > defaults["device_ingest_max_body_bytes"].default:
        raise SystemExit("firmware example exceeds the default body byte limit")
    if not parsed.is_test_data:
        raise SystemExit(
            "firmware protocol example must remain explicitly marked as test data"
        )
    if not parsed.records:
        raise SystemExit("firmware protocol example must contain at least one record")
    for record in parsed.records:
        _normalize_protocol_record(
            record_type=record.type,
            occurred_at_raw=record.occurred_at,
            raw_payload=record.payload,
            is_test_data=parsed.is_test_data,
            firmware_version=parsed.firmware_version,
            server_received_at=datetime.now(timezone.utc),
        )
    print(
        "firmware protocol consistency passed: "
        f"version={compiled_version}, records={len(parsed.records)}"
    )


if __name__ == "__main__":
    main()
