"""Command line entry point."""

from __future__ import annotations

import argparse
import json
import os
import signal
import sys
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from threading import Event
from typing import Optional

import serial

from .batcher import BatchBuilder, PendingBatch
from .parser import parse_line
from .runtime import BatchDispatcher, replay_file
from .transport import Sender


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="ESP32-S3 SHT31 serial bridge")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--port", help="serial device, for example /dev/cu.usbmodem1201")
    mode.add_argument("--replay", type=Path, help="saved UTF-8 serial text")
    parser.add_argument("--baud", type=int, default=115200)
    parser.add_argument("--base-url", default="http://localhost:8000")
    parser.add_argument("--device-id", default=None)
    parser.add_argument("--session-id", default=None)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--is-test-data", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--batch-size", type=int, default=50)
    parser.add_argument("--flush-seconds", type=float, default=5.0)
    parser.add_argument("--max-queued-batches", type=int, default=20)
    parser.add_argument("--reconnect", action="store_true")
    parser.add_argument("--firmware-version", default=None)
    return parser


def _output_batch(batch: PendingBatch) -> bool:
    print(json.dumps(batch.payload, ensure_ascii=False, separators=(",", ":")), flush=True)
    return True


@contextmanager
def _sigterm_requested():
    """Turn SIGTERM into the same cooperative shutdown used by Ctrl-C."""
    requested = Event()
    previous = signal.getsignal(signal.SIGTERM)

    def handle_sigterm(_signum, _frame):
        requested.set()

    signal.signal(signal.SIGTERM, handle_sigterm)
    try:
        yield requested
    finally:
        signal.signal(signal.SIGTERM, previous)


def _run_replay(args: argparse.Namespace, builder: BatchBuilder, sender: Optional[Sender]) -> int:
    with _sigterm_requested() as stop_requested:
        dispatcher = (
            None
            if args.dry_run
            else BatchDispatcher(
                sender,
                max_batches=args.max_queued_batches,
                report=lambda msg: print(msg, file=sys.stderr),
            )
        )
        generated = 0

        def emit(batch: PendingBatch) -> bool:
            nonlocal generated
            generated += 1
            if dispatcher is None:
                return _output_batch(batch)
            dispatcher.submit(batch)
            return True

        if dispatcher is not None:
            dispatcher.start()
        try:
            replay_file(
                args.replay,
                builder=builder,
                emit_batch=emit,
                should_stop=lambda: stop_requested.is_set()
                or (dispatcher is not None and dispatcher.auth_error),
            )
        except KeyboardInterrupt:
            pass
        finally:
            batch = builder.flush(force=True)
            if batch:
                emit(batch)
            if dispatcher is not None:
                _, unsent, _ = dispatcher.finish(timeout=15.0)
                dispatcher.report_summary(unsent=unsent)
            else:
                print(
                    f"serial bridge shutdown (dry-run): sent={generated}, unsent=0, discarded=0",
                    file=sys.stderr,
                )
        return 2 if dispatcher is not None and dispatcher.auth_error else 0


def _open_serial(port: str, baud: int):
    # Open first (the native USB bridge tolerates DTR=RTS=1), then release RTS
    # before DTR so no intermediate control-line state resets the ESP32-S3.
    connection = serial.Serial(port, baud, timeout=1)
    try:
        connection.rts = False
        connection.dtr = False
    except BaseException:
        _close_serial(connection)
        raise
    return connection


def _close_serial(connection) -> None:
    """Release RTS then DTR before closing, avoiding a USB-JTAG reset pulse."""
    try:
        connection.rts = False
    finally:
        try:
            connection.dtr = False
        finally:
            connection.close()


def _run_live(args: argparse.Namespace, builder: BatchBuilder, sender: Optional[Sender]) -> int:
    with _sigterm_requested() as stop_requested:
        dispatcher = (
            None
            if args.dry_run
            else BatchDispatcher(
                sender,
                max_batches=args.max_queued_batches,
                report=lambda msg: print(msg, file=sys.stderr),
            )
        )
        generated = 0

        def emit(batch: PendingBatch) -> bool:
            nonlocal generated
            generated += 1
            if dispatcher is None:
                return _output_batch(batch)
            dispatcher.submit(batch)
            return True

        def auth_failed() -> bool:
            return dispatcher is not None and dispatcher.auth_error

        def handle_complete_line(raw_line: bytes) -> None:
            nonlocal unknown_count
            received_at = datetime.now(timezone.utc)
            text = raw_line.decode("utf-8", errors="replace")
            echo_stream = sys.stderr if args.dry_run else sys.stdout
            echo_stream.write(text)
            echo_stream.flush()
            parsed = parse_line(text)
            if parsed is None:
                unknown_count += 1
                print(f"unrecognized serial line: {text!r}", file=sys.stderr)
                return
            for batch in builder.add(parsed, received_at=received_at):
                emit(batch)

        unknown_count = 0
        partial_count = 0
        result = 0
        if dispatcher is not None:
            dispatcher.start()
        try:
            while not auth_failed() and not stop_requested.is_set():
                connection = None
                byte_buffer = bytearray()
                try:
                    connection = _open_serial(args.port, args.baud)
                    print(f"serial bridge connected: {args.port}", file=sys.stderr)
                    while not auth_failed() and not stop_requested.is_set():
                        raw = connection.read(256)
                        byte_buffer.extend(raw)
                        while (
                            b"\n" in byte_buffer
                            and not auth_failed()
                            and not stop_requested.is_set()
                        ):
                            line, _, rest = byte_buffer.partition(b"\n")
                            byte_buffer = bytearray(rest)
                            handle_complete_line(line + b"\n")
                        if (
                            builder.should_flush()
                            and not auth_failed()
                            and not stop_requested.is_set()
                        ):
                            batch = builder.flush()
                            if batch:
                                emit(batch)
                except (OSError, serial.SerialException) as exc:
                    if not stop_requested.is_set():
                        print(f"serial bridge disconnected: {type(exc).__name__}", file=sys.stderr)
                        if not args.reconnect:
                            result = 1
                            break
                finally:
                    if byte_buffer:
                        partial_count += 1
                        print(
                            f"discarded incomplete serial data on close (total={partial_count})",
                            file=sys.stderr,
                        )
                    if connection is not None:
                        _close_serial(connection)
                if args.reconnect and not auth_failed() and not stop_requested.is_set():
                    time.sleep(1.0)
        except KeyboardInterrupt:
            pass
        finally:
            batch = builder.flush(force=True)
            if batch:
                emit(batch)
            if unknown_count:
                print(f"unrecognized serial lines: {unknown_count}", file=sys.stderr)
            if partial_count:
                print(f"partial serial lines discarded: {partial_count}", file=sys.stderr)
            if dispatcher is not None:
                _, unsent, _ = dispatcher.finish(timeout=15.0)
                dispatcher.report_summary(unsent=unsent)
            else:
                print(
                    f"serial bridge shutdown (dry-run): sent={generated}, unsent=0, discarded=0",
                    file=sys.stderr,
                )
        return 2 if auth_failed() else result


def main(argv: Optional[list[str]] = None) -> int:
    args = _build_parser().parse_args(argv)
    firmware_version = (
        args.firmware_version
        or Path(__file__)
        .resolve()
        .parents[2]
        .joinpath("firmware", "esp32s3_sht31", "VERSION")
        .read_text(encoding="utf-8")
        .strip()
    )
    builder = BatchBuilder(
        max_records=args.batch_size,
        interval_seconds=args.flush_seconds,
        firmware_version=firmware_version,
        is_test_data=args.is_test_data,
        replay=args.replay is not None,
    )
    sender = None
    if not args.dry_run:
        token = os.environ.get("XJ_DEVICE_TOKEN")
        if not token:
            print("XJ_DEVICE_TOKEN environment variable is required", file=sys.stderr)
            return 2
        if not args.device_id:
            print("--device-id is required unless --dry-run is used", file=sys.stderr)
            return 2
        sender = Sender(
            base_url=args.base_url,
            device_id=args.device_id,
            token=token,
            session_id=args.session_id,
            report=lambda msg: print(msg, file=sys.stderr),
        )
    if args.replay:
        return _run_replay(args, builder, sender)
    return _run_live(args, builder, sender)


if __name__ == "__main__":
    raise SystemExit(main())
