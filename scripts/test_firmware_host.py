"""Compile production firmware transport/store against host I/O fault adapters.

Requires the locked ArduinoJson library installed by `pio pkg install`/`pio run`.
This does not simulate flash durability or prove physical hardware behavior.
"""

import os
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FIRMWARE = ROOT / "firmware/esp32_dht11"


def main():
    library = FIRMWARE / ".pio/libdeps/esp32dev/ArduinoJson/src"
    if not library.is_dir():
        raise SystemExit(
            "ArduinoJson missing: run pio pkg install -d firmware/esp32_dht11 first"
        )
    host = FIRMWARE / "tests/host"
    with tempfile.TemporaryDirectory(prefix="xinjian-firmware-host-") as tmp:
        for serial_only in (False, True):
            binary = Path(tmp) / ("serial" if serial_only else "transport")
            command = [
                os.environ.get("CXX", "c++"),
                "-std=c++17",
                "-Wall",
                "-Wextra",
                f"-I{host}",
                f"-I{library}",
                f"-I{FIRMWARE / 'include'}",
            ]
            if serial_only:
                command += ["-DSERIAL_ONLY=1"]
            subprocess.run(
                command
                + [
                    str(host / "transport_test.cpp"),
                    str(FIRMWARE / "src/pending_store.cpp"),
                    "-o",
                    str(binary),
                ],
                check=True,
            )
            subprocess.run([str(binary)], check=True)


if __name__ == "__main__":
    main()
