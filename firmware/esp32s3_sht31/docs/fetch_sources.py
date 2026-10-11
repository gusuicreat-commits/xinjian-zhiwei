"""Fetch only the registered official sources and verify their SHA-256 hashes."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[3]
REGISTRY = Path(__file__).with_name("sources.json")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-root", type=Path, default=ROOT)
    args = parser.parse_args()
    registry = json.loads(REGISTRY.read_text(encoding="utf-8"))
    for source in registry["sources"]:
        destination = args.output_root / source["local_raw"]
        destination.parent.mkdir(parents=True, exist_ok=True)
        request = Request(source["url"], headers={"User-Agent": "xinjian-source-audit/1.0"})
        with urlopen(request, timeout=30) as response:
            data = response.read()
        actual = hashlib.sha256(data).hexdigest()
        if actual != source["sha256"]:
            raise SystemExit(f"hash mismatch for {source['id']}: {actual}")
        destination.write_bytes(data)
        print(f"verified {source['id']} sha256={actual}")


if __name__ == "__main__":
    main()
