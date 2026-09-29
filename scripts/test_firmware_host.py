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
        decoder = Path(tmp) / "decoder"
        subprocess.run(
            [
                os.environ.get("CXX", "c++"),
                "-std=c++17",
                "-Wall",
                "-Wextra",
                f"-I{host}",
                f"-I{library}",
                f"-I{FIRMWARE / 'include'}",
                str(host / "decoder_test.cpp"),
                str(FIRMWARE / "src/dht11_reader.cpp"),
                str(FIRMWARE / "src/pending_store.cpp"),
                "-o",
                str(decoder),
            ],
            check=True,
        )
        subprocess.run([str(decoder)], check=True)
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

        failures = []
        for allow_http in (0, 1):
            binary = Path(tmp) / f"scheduling-policy-{allow_http}"
            subprocess.run(
                [os.environ.get("CXX", "c++"), "-std=c++17", "-Wall", "-Wextra",
                 f"-I{host}", f"-I{library}", f"-I{FIRMWARE / 'include'}",
                 f"-DXJ_ALLOW_INSECURE_HTTP={allow_http}",
                 str(host / "scheduling_policy_test.cpp"),
                 str(FIRMWARE / "src/pending_store.cpp"), "-o", str(binary)],
                check=True,
            )
            scenarios = ["https-ca", "https-empty", "http", "invalid-scheme"]
            if not allow_http:
                scenarios += ["boundary", "serial-boundary", "retry-fast", "retry-slow", "retry-prime-fast", "retry-prime",
                              "initial-slow", "retry-failure", "startup", "failure-recovery"]
            for scenario in scenarios:
                result = subprocess.run([str(binary), scenario], check=False)
                if result.returncode:
                    failures.append((allow_http, scenario, result.returncode))
        if failures:
            raise SystemExit(f"Firmware regression failures: {failures}")


if __name__ == "__main__":
    main()
