from datetime import datetime, timezone

from xinjian_serial_bridge.batcher import BatchBuilder
from xinjian_serial_bridge.parser import parse_line


def test_generated_batch_has_backend_v1_shape_without_backend_imports():
    builder = BatchBuilder(replay=False)
    received = datetime(2026, 10, 11, tzinfo=timezone.utc)
    builder.add(parse_line("SHT31 传感器启动!"), received_at=received)
    builder.add(parse_line("温度: 25.29 ℃ | 湿度: 42.06 %RH"), received_at=received)
    payload = builder.flush(force=True).payload
    assert payload["protocolVersion"] == "1.0"
    assert payload["schemaVersion"] == "1"
    assert payload["isTestData"] is True
    assert 1 <= len(payload["records"]) <= 100
    assert all(record["type"] in {"reading", "log", "heartbeat"} for record in payload["records"])
