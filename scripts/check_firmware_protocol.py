"""Validate only the computer serial bridge protocol sample (legacy entry point)."""

import json
import runpy
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BRIDGE = ROOT / "bridge"


def main():
    checker = runpy.run_path(str(ROOT / "scripts/check_serial_bridge_protocol.py"))
    payload = json.loads((BRIDGE / "docs/protocol-example.json").read_text())
    checker["validate"](payload)
    print("bridge protocol sample passed")


if __name__ == "__main__":
    main()
