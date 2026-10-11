import os
import signal

from xinjian_serial_bridge import cli
from xinjian_serial_bridge.batcher import BatchBuilder


class FakeSerial:
    def __init__(self):
        self.lines = [b"SHT31 \xe4\xbc\xa0\xe6\x84\x9f\xe5\x99\xa8\xe5\x90\xaf\xe5\x8a\xa8!\n"]
        self.closed = False

    def read(self, _size):
        if self.lines:
            return self.lines.pop(0)
        raise KeyboardInterrupt

    def close(self):
        self.closed = True


class ChunkSerial:
    def __init__(self, chunks):
        self.chunks = list(chunks)
        self.closed = False
        self.read_calls = 0

    def read(self, _size):
        self.read_calls += 1
        if self.chunks:
            chunk = self.chunks.pop(0)
            if isinstance(chunk, BaseException):
                raise chunk
            return chunk
        raise KeyboardInterrupt

    def close(self):
        self.closed = True


def test_live_loop_fake_serial_flushes_pending(capsys, monkeypatch):
    fake = FakeSerial()
    monkeypatch.setattr(cli, "_open_serial", lambda _port, _baud: fake)
    args = type("Args", (), {"dry_run": True, "port": "fake", "baud": 115200, "reconnect": False})()
    builder = BatchBuilder(replay=False)
    assert cli._run_live(args, builder, None) == 0
    assert fake.closed
    captured = capsys.readouterr()
    assert "SHT31 传感器启动!" in captured.err
    assert '"event_code":"SHT31_BOOT"' in captured.out


def test_live_loop_accumulates_byte_chunks_until_newline(capsys, monkeypatch):
    fake = ChunkSerial(
        [
            "温度: 26.56 ℃ | 湿度: ".encode(),
            "40.80 %RH\nSHT31 传感器启动!\n".encode(),
        ]
    )
    monkeypatch.setattr(cli, "_open_serial", lambda _port, _baud: fake)
    args = type(
        "Args",
        (),
        {"dry_run": True, "port": "fake", "baud": 115200, "reconnect": False},
    )()
    assert cli._run_live(args, BatchBuilder(replay=False), None) == 0
    captured = capsys.readouterr()
    assert "unrecognized serial line" not in captured.err
    assert '"metric_key":"temperature"' in captured.out
    assert '"event_code":"SHT31_BOOT"' in captured.out
    assert fake.read_calls == 3


def test_live_loop_discards_and_reports_partial_line_on_disconnect(capsys, monkeypatch):
    fake = ChunkSerial(["温度: 26.56 ℃ | 湿度:".encode(), OSError("gone")])
    monkeypatch.setattr(cli, "_open_serial", lambda _port, _baud: fake)
    args = type(
        "Args",
        (),
        {"dry_run": True, "port": "fake", "baud": 115200, "reconnect": False},
    )()
    assert cli._run_live(args, BatchBuilder(replay=False), None) == 1
    captured = capsys.readouterr()
    assert "partial serial lines discarded: 1" in captured.err
    assert "26.56" not in captured.out


def test_split_utf8_and_timeout_do_not_discard_partial_line(capsys, monkeypatch):
    raw = "  温度: -3.25 ℃ | 湿度: 42.06 %RH  \r\n".encode()
    fake = ChunkSerial([raw[:3], b"", raw[3:19], b"", raw[19:]])
    monkeypatch.setattr(cli, "_open_serial", lambda *_: fake)
    args = type(
        "Args",
        (),
        {
            "dry_run": True,
            "port": "fake",
            "baud": 115200,
            "reconnect": False,
        },
    )()
    assert cli._run_live(args, BatchBuilder(), None) == 0
    captured = capsys.readouterr()
    assert "unrecognized" not in captured.err
    assert raw.decode() in captured.err
    assert '"value":-3.25' in captured.out
    assert '"value":42.06' in captured.out
    assert "sent=1, unsent=0, discarded=0" in captured.err


def test_reconnect_never_combines_fragments_from_two_connections(capsys, monkeypatch):
    old = ChunkSerial(["温度: 26.56 ℃ | 湿度:".encode(), OSError("gone")])
    new = ChunkSerial(
        [b"40.80 %RH\n", b"SHT31 \xe4\xbc\xa0\xe6\x84\x9f\xe5\x99\xa8\xe5\x90\xaf\xe5\x8a\xa8!\n"]
    )
    streams = iter([old, new])
    monkeypatch.setattr(cli, "_open_serial", lambda *_: next(streams))
    monkeypatch.setattr(cli.time, "sleep", lambda _: None)
    args = type(
        "Args",
        (),
        {
            "dry_run": True,
            "port": "fake",
            "baud": 115200,
            "reconnect": True,
        },
    )()
    assert cli._run_live(args, BatchBuilder(), None) == 0
    captured = capsys.readouterr()
    assert old.closed and new.closed
    assert '"type":"reading"' not in captured.out
    assert '"event_code":"SHT31_BOOT"' in captured.out
    assert "partial serial lines discarded: 1" in captured.err


def test_serial_controls_open_and_close_in_safe_order(monkeypatch):
    events = []

    class Port:
        def __init__(self, port, baud, timeout):
            assert (port, baud, timeout) == ("fake", 115200, 1)
            self._dtr = True
            self._rts = True
            events.append(("open", self.dtr, self.rts))

        @property
        def dtr(self):
            return self._dtr

        @dtr.setter
        def dtr(self, value):
            self._dtr = value
            events.append(("dtr", value, self.rts))

        @property
        def rts(self):
            return self._rts

        @rts.setter
        def rts(self, value):
            self._rts = value
            events.append(("rts", self.dtr, value))

        def close(self):
            events.append(("close", self.dtr, self.rts))

    monkeypatch.setattr(cli.serial, "Serial", Port)
    connection = cli._open_serial("fake", 115200)
    cli._close_serial(connection)

    assert [event[0] for event in events] == ["open", "rts", "dtr", "rts", "dtr", "close"]
    assert events[1:3] == [("rts", True, False), ("dtr", False, False)]
    assert events[3:5] == [("rts", False, False), ("dtr", False, False)]
    assert all(not (rts and not dtr) for _, dtr, rts in events)


def test_reconnect_releases_rts_before_dtr_on_every_close(capsys, monkeypatch):
    class TracedSerial(ChunkSerial):
        def __init__(self, chunks):
            super().__init__(chunks)
            self._dtr = True
            self._rts = True
            self.control_events = [("open", self.dtr, self.rts)]

        @property
        def dtr(self):
            return self._dtr

        @dtr.setter
        def dtr(self, value):
            self._dtr = value
            self.control_events.append(("dtr", value, self.rts))

        @property
        def rts(self):
            return self._rts

        @rts.setter
        def rts(self, value):
            self._rts = value
            self.control_events.append(("rts", self.dtr, value))

    old = TracedSerial([OSError("gone")])
    new = TracedSerial([KeyboardInterrupt()])
    streams = iter([old, new])
    monkeypatch.setattr(cli, "_open_serial", lambda *_: next(streams))
    monkeypatch.setattr(cli.time, "sleep", lambda _: None)
    args = type(
        "Args",
        (),
        {"dry_run": True, "port": "fake", "baud": 115200, "reconnect": True},
    )()

    assert cli._run_live(args, BatchBuilder(), None) == 0
    assert old.control_events[1:] == [("rts", True, False), ("dtr", False, False)]
    assert new.control_events[1:] == [("rts", True, False), ("dtr", False, False)]
    for stream in (old, new):
        assert all(not (rts and not dtr) for _, dtr, rts in stream.control_events)


def test_sigterm_uses_normal_shutdown_summary(capsys, monkeypatch):
    class TerminatingSerial:
        def __init__(self):
            self._dtr = True
            self._rts = True
            self.control_events = [("open", self.dtr, self.rts)]

        @property
        def dtr(self):
            return self._dtr

        @dtr.setter
        def dtr(self, value):
            self._dtr = value
            self.control_events.append(("dtr", value, self.rts))

        @property
        def rts(self):
            return self._rts

        @rts.setter
        def rts(self, value):
            self._rts = value
            self.control_events.append(("rts", self.dtr, value))

        def read(self, _size):
            os.kill(os.getpid(), signal.SIGTERM)
            return b""

        def close(self):
            self.control_events.append(("close", self.dtr, self.rts))

    stream = TerminatingSerial()
    monkeypatch.setattr(cli, "_open_serial", lambda *_: stream)
    args = type(
        "Args",
        (),
        {"dry_run": True, "port": "fake", "baud": 115200, "reconnect": False},
    )()

    assert cli._run_live(args, BatchBuilder(), None) == 0
    assert (
        "serial bridge shutdown (dry-run): sent=0, unsent=0, discarded=0"
        in capsys.readouterr().err
    )
    assert stream.control_events[1:3] == [("rts", True, False), ("dtr", False, False)]
