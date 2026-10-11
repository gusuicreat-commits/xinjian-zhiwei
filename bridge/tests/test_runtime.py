import io
import json

from xinjian_serial_bridge.batcher import BatchBuilder
from xinjian_serial_bridge.runtime import process_lines


def test_unknown_lines_are_not_uploaded_and_dry_run_batches_are_json():
    output = []
    errors = io.StringIO()
    builder = BatchBuilder(replay=True)
    sent = process_lines(
        [
            "ESP-ROM:esp32s3-20210327\n",
            "SHT31 传感器启动!\n",
            "温度: 26.56 ℃ | 湿度: 40.80 %RH\n",
            "读取失败！检查接线或者把地址改成0x45\n",
            "半行乱码�",
        ],
        builder=builder,
        emit_batch=lambda batch: output.append(batch.payload) or True,
        stderr=errors,
    )
    assert sent == 1
    assert len(output) == 1
    payload = output[0]
    json.dumps(payload, ensure_ascii=False)
    assert payload["isTestData"] is True
    assert len(payload["records"]) == 5
    assert "ESP-ROM" in errors.getvalue()
    assert "半行乱码" in errors.getvalue()


def test_replay_eof_finishes_with_summary(tmp_path, capsys):
    from argparse import Namespace

    import httpx

    from xinjian_serial_bridge import cli
    from xinjian_serial_bridge.transport import Sender

    path = tmp_path / "serial.txt"
    path.write_text("SHT31 传感器启动!\n", encoding="utf-8")
    seen = []

    def handler(request):
        payload = json.loads(request.content)
        seen.append(payload)
        return httpx.Response(
            201,
            json={
                "requestId": payload["requestId"],
                "records": payload["records"],
            },
        )

    sender = Sender(
        base_url="http://example.test",
        device_id="device",
        token="private",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    args = Namespace(dry_run=False, replay=path, max_queued_batches=5)
    assert cli._run_replay(args, BatchBuilder(replay=True), sender) == 0
    assert len(seen) == 1
    assert "sent=1, unsent=0, discarded=0" in capsys.readouterr().err


def test_replay_keyboard_interrupt_flushes_and_summarizes(capsys, monkeypatch):
    from argparse import Namespace

    from xinjian_serial_bridge import cli
    from xinjian_serial_bridge.parser import parse_line

    def interrupted(path, *, builder, **kwargs):
        builder.add(parse_line("SHT31 传感器启动!"), received_at=None)
        raise KeyboardInterrupt

    monkeypatch.setattr(cli, "replay_file", interrupted)
    args = Namespace(dry_run=True, replay="fake")
    assert cli._run_replay(args, BatchBuilder(replay=True), None) == 0
    captured = capsys.readouterr()
    assert '"event_code":"SHT31_BOOT"' in captured.out
    assert "sent=1, unsent=0, discarded=0" in captured.err
