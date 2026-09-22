"""Fetch the fixed official-source allowlist and verify its recorded hashes.

This is deliberately an allowlist fetcher, not a site crawler. Raw documents are
kept outside git because they may be copyrighted or change independently.
"""

from __future__ import annotations

import argparse
import hashlib
from pathlib import Path
from urllib.request import Request, urlopen


SOURCES = {
    "aosong-dht11-v1.3.pdf": (
        "https://www.aosong.com/userfiles/files/media/"
        "DHT11-V1_3%E8%AF%B4%E6%98%8E%E4%B9%A6%EF%BC%88%E8%AF%A6%E7%BB%86%E7%89%88%EF%BC%89.pdf",
        "1702de1e17328b98275d381404d27592b3f8da274b27df30b6caf42e6d3b0f16",
    ),
    "platform-espressif32-7.0.1.json": (
        "https://raw.githubusercontent.com/platformio/platform-espressif32/v7.0.1/platform.json",
        "cfd206f4dabb664c5485124d5d9049e19abdcd807e144cf4e615205f96b0ae01",
    ),
    "adafruit-dht-cpp-1.4.6": (
        "https://raw.githubusercontent.com/adafruit/DHT-sensor-library/1.4.6/DHT.cpp",
        "244dcbf3a69b2f70fcef39632a3dd65f3af9869142ea93d6bb9dd99a54f7a6fd",
    ),
    "arduinojson-7.4.2.json": (
        "https://raw.githubusercontent.com/bblanchon/ArduinoJson/v7.4.2/library.json",
        "39309b243592657a63225549850c911d48edeb7659179e8be69605c923861585",
    ),
    "esp32-devkitc-user-guide.html": (
        "https://docs.espressif.com/projects/esp-dev-kits/en/latest/esp32/esp32-devkitc/user_guide.html",
        "0a9c01dcff30d31c6ff51294c22650b44bfe9cec4a633d59b73667f6d18572e5",
    ),
}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=Path("data/knowledge/raw/esp32-dht11"))
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    for filename, (url, expected_hash) in SOURCES.items():
        request = Request(url, headers={"User-Agent": "xinjian-source-audit/1.0"})
        with urlopen(request, timeout=30) as response:
            data = response.read()
        actual_hash = hashlib.sha256(data).hexdigest()
        if actual_hash != expected_hash:
            raise SystemExit(f"hash mismatch for {filename}: {actual_hash}")
        (args.output / filename).write_bytes(data)
        print(f"verified {filename} sha256={actual_hash}")


if __name__ == "__main__":
    main()
