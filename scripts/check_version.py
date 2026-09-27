"""Check application versions and package changes against an explicit Git baseline."""

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import yaml
from packaging.version import Version

try:
    import tomllib
except ModuleNotFoundError:
    import tomli as tomllib

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

from app.experiment_packages.loader import (  # noqa: E402
    PACKAGE_FILES,
    _manifest_for_documents,
    _read_documents,
)

# Only these current-status statements are checked. Dated historical reports
# and examples must retain their historical versions.
DOC_VERSIONS = {
    "README.md": {
        "dht11_temperature_humidity": [
            r"DHT11 资料包是 \*\*`([^`]+)`",
            r"DHT11 温湿度 `([^`]+)`",
        ],
        "gpio_led_output": [r"GPIO LED `([^`]+)`"],
    },
    "docs/project-truth-status.md": {
        "dht11_temperature_humidity": [r"DHT11 工作区 `([^`]+)`"],
        "gpio_led_output": [r"LED 工作区 `([^`]+)`"],
    },
    "docs/implementation-status.md": {
        "dht11_temperature_humidity": [r"`dht11_temperature_humidity@([^`]+)`"],
        "gpio_led_output": [r"`gpio_led_output@([^`]+)`"],
    },
}


def git(root, *args):
    result = subprocess.run(
        ["git", "-C", str(root), *args], capture_output=True, text=True
    )
    if result.returncode:
        raise ValueError("version baseline unavailable: " + result.stderr.strip())
    return result.stdout


def package_state(directory):
    documents, manifest = _read_documents(directory)
    metadata = documents["metadata.yaml"]
    code, version = metadata["experiment"]["code"], metadata["package"]["version"]
    if (
        code != directory.name
        or not isinstance(version, str)
        or not re.fullmatch(r"\d+\.\d+\.\d+", version)
    ):
        raise ValueError(f"invalid package identity/version: {directory}")
    return {"version": version, "sha256": manifest.package_hash}


def check(root: Path, base_ref: str):
    # Pin a commit, not a moving name. A missing/shallow baseline is a failure.
    baseline = git(root, "rev-parse", "--verify", f"{base_ref}^{{commit}}").strip()
    expected = (root / "VERSION").read_text().strip()
    versions = {
        name: tomllib.loads((root / name / "pyproject.toml").read_text())["project"][
            "version"
        ]
        for name in ("backend", "simulator")
    }
    versions["frontend"] = json.loads((root / "frontend/package.json").read_text())[
        "version"
    ]
    for name, rel, pattern in (
        (
            "simulator_runtime",
            "simulator/xinjian_simulator/__init__.py",
            r'__version__\s*=\s*"([^"]+)"',
        ),
        (
            "backend_runtime",
            "backend/app/core/config.py",
            r'app_version: str = "([^"]+)"',
        ),
    ):
        match = re.search(pattern, (root / rel).read_text())
        versions[name] = match.group(1) if match else None
    if any(value != expected for value in versions.values()):
        raise ValueError(
            f"application version mismatch expected={expected}: {versions}"
        )

    package_root = root / "backend/experiment_packages"
    current = {
        p.name: package_state(p) for p in sorted(package_root.iterdir()) if p.is_dir()
    }
    recorded = json.loads((root / "scripts/package_versions.json").read_text())
    if current != recorded:
        raise ValueError(
            "package manifest differs from content; review version and update manifest"
        )

    base_paths = git(
        root, "ls-tree", "-r", "--name-only", baseline, "backend/experiment_packages"
    ).splitlines()
    old_packages = {p.split("/")[2] for p in base_paths if p.endswith("/metadata.yaml")}
    if old_packages - current.keys():
        raise ValueError(
            "package removal requires a separately reviewed compatibility change"
        )
    for code in old_packages:
        documents = {
            path: yaml.safe_load(
                git(
                    root,
                    "show",
                    f"{baseline}:backend/experiment_packages/{code}/{path}",
                )
            )
            for path in PACKAGE_FILES
        }
        old_version = documents["metadata.yaml"]["package"]["version"]
        old_hash = _manifest_for_documents(documents).package_hash
        new = current[code]
        if old_hash != new["sha256"] and Version(new["version"]) <= Version(
            old_version
        ):
            raise ValueError(
                f"package {code} changed without a version increase from {old_version}"
            )
    for filename, packages in DOC_VERSIONS.items():
        content = (root / filename).read_text()
        for code, patterns in packages.items():
            for pattern in patterns:
                matches = re.findall(pattern, content)
                if matches != [current[code]["version"]]:
                    raise ValueError(
                        f"current documentation version mismatch: {filename}: {code}"
                    )
    return expected, current, baseline


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--base-ref", default=os.environ.get("VERSION_BASE_REF", "HEAD")
    )
    args = parser.parse_args()
    try:
        app, packages, baseline = check(ROOT, args.base_ref)
    except (ValueError, KeyError, OSError) as exc:
        raise SystemExit(str(exc)) from exc
    print(
        f"version consistency passed: app={app}; packages={packages}; baseline={baseline}"
    )


if __name__ == "__main__":
    main()
