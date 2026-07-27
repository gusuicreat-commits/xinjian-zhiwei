import json
import re
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:
    import tomli as tomllib

ROOT = Path(__file__).resolve().parent.parent
expected = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
versions = {
    "backend_pyproject": tomllib.loads(
        (ROOT / "backend/pyproject.toml").read_text(encoding="utf-8")
    )["project"]["version"],
    "simulator_pyproject": tomllib.loads(
        (ROOT / "simulator/pyproject.toml").read_text(encoding="utf-8")
    )["project"]["version"],
    "frontend_package": json.loads(
        (ROOT / "frontend/package.json").read_text(encoding="utf-8")
    )["version"],
}
init_text = (ROOT / "simulator/xinjian_simulator/__init__.py").read_text(encoding="utf-8")
match = re.search(r'__version__\s*=\s*"([^"]+)"', init_text)
versions["simulator_runtime"] = match.group(1) if match else ""
config_text = (ROOT / "backend/app/core/config.py").read_text(encoding="utf-8")
versions["backend_runtime"] = config_text.split('app_version: str = "')[1].split('"')[0]

mismatches = {name: value for name, value in versions.items() if value != expected}
if mismatches:
    raise SystemExit(f"version mismatch expected={expected}: {mismatches}")
print(f"version consistency passed: {expected}")
