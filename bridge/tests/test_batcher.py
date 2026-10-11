from xinjian_serial_bridge.batcher import BatchBuilder, BoundedBatchQueue
from xinjian_serial_bridge.parser import parse_line


def _reading():
    return parse_line("温度: 26.56 ℃ | 湿度: 40.80 %RH")


def test_boot_changes_id_and_resets_sequence_and_heartbeat_needs_activity():
    builder = BatchBuilder(max_records=10, replay=True)
    old_boot = builder.boot_id
    assert builder.flush(force=True) is None
    builder.add(_reading(), received_at=None)
    first = builder.flush(force=True).payload
    assert first["sequenceNo"] == 0
    assert any(r["type"] == "heartbeat" for r in first["records"])
    builder.add(parse_line("SHT31 传感器启动!"), received_at=None)
    second = builder.flush(force=True).payload
    assert second["bootId"] != old_boot
    assert second["sequenceNo"] == 0
    assert second["records"][0]["payload"]["event_code"] == "SHT31_BOOT"
    assert all("occurredAt" not in record for record in first["records"])
    assert first["records"][0]["payload"]["metadata"]["time_source"] == "replay_unknown"


def test_queue_reports_oldest_discard():
    messages = []
    queue = BoundedBatchQueue(1, report=messages.append)
    builder = BatchBuilder(replay=True)
    builder.add(_reading(), received_at=None)
    first = builder.flush(force=True)
    builder.add(_reading(), received_at=None)
    second = builder.flush(force=True)
    queue.put(first)
    queue.put(second)
    assert len(queue) == 1
    assert queue.discarded_batches == 1
    assert "discarded 1 batch" in messages[0]


def test_elapsed_timer_batches_and_silence_never_generates_heartbeat():
    clock = [0.0]
    builder = BatchBuilder(clock=lambda: clock[0], interval_seconds=5)
    builder.add(_reading(), received_at=None)
    clock[0] = 4.9
    assert builder.flush() is None
    clock[0] = 5
    payload = builder.flush().payload
    assert [record["type"] for record in payload["records"]] == [
        "reading",
        "reading",
        "heartbeat",
    ]
    clock[0] = 500
    assert not builder.should_flush()
    assert builder.flush(force=True) is None


def test_full_batches_stay_below_record_and_utf8_byte_limits():
    import json

    batches = []
    builder = BatchBuilder(max_records=100, replay=True)
    for _ in range(100):
        batches.extend(builder.add(_reading(), received_at=None))
    batches.append(builder.flush(force=True))
    assert len(batches[0].payload["records"]) == 100
    assert all(1 <= len(batch.payload["records"]) <= 100 for batch in batches)
    assert all(len(json.dumps(batch.payload).encode()) <= 262144 for batch in batches)
