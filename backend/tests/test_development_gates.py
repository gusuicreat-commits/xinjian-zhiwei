"""Mutation tests: gates must reject data the real runtime cannot accept."""

import importlib.util
import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def script(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize(
    "mutation",
    ["missing", "type", "nan", "inf", "empty", "version", "too_many", "too_large", "valid"],
)
def test_firmware_gate_validates_actual_records(tmp_path, mutation):
    module = script("check_firmware_protocol")
    for rel in ("docs/protocol-example.json",):
        target = tmp_path / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(module.BRIDGE / rel, target)
    example = tmp_path / "docs/protocol-example.json"
    data = json.loads(example.read_text())
    reading = data["records"][1]["payload"]
    if mutation == "missing":
        reading.pop("value")
    elif mutation in {"type", "nan", "inf"}:
        reading["value"] = {"type": "bad", "nan": float("nan"), "inf": float("inf")}[mutation]
    elif mutation == "empty":
        data["records"] = []
    elif mutation == "too_many":
        data["records"] = [data["records"][1]] * 101
    elif mutation == "too_large":
        reading["metadata"] = {"large": "x" * 1000000}
    elif mutation == "version":
        data["protocolVersion"] = "future-unsupported"
    else:
        for record in data["records"]:
            record.pop("occurredAt", None)  # No NTP is a supported firmware mode.
    example.write_text(json.dumps(data))
    module.BRIDGE = tmp_path
    if mutation == "valid":
        module.main()
    else:
        with pytest.raises((ValueError, SystemExit)):
            module.main()


@pytest.fixture
def version_repo(tmp_path):
    paths = [
        "VERSION",
        "backend/pyproject.toml",
        "simulator/pyproject.toml",
        "frontend/package.json",
        "simulator/xinjian_simulator/__init__.py",
        "backend/app/core/config.py",
        "README.md",
        "docs/project-truth-status.md",
        "docs/implementation-status.md",
        "scripts/package_versions.json",
    ]
    for rel in paths:
        target = tmp_path / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / rel, target)
    manifest = tmp_path / "scripts/package_versions.json"
    recorded = json.loads(manifest.read_text())
    recorded.pop("replacements", None)
    manifest.write_text(json.dumps(recorded))
    shutil.copytree(ROOT / "backend/experiment_packages", tmp_path / "backend/experiment_packages")
    for arguments in (
        ["init", "-q"],
        ["add", "."],
        [
            "-c",
            "user.name=Test",
            "-c",
            "user.email=test@example.invalid",
            "-c",
            "commit.gpgsign=false",
            "-c",
            "core.hooksPath=/dev/null",
            "commit",
            "-qm",
            "isolated baseline",
        ],
    ):
        subprocess.run(["git", "-C", str(tmp_path), *arguments], check=True, capture_output=True)
    return tmp_path, script("check_version")


def update_manifest(root, module):
    packages = root / "backend/experiment_packages"
    state = {p.name: module.package_state(p) for p in packages.iterdir() if p.is_dir()}
    manifest = root / "scripts/package_versions.json"
    recorded = json.loads(manifest.read_text())
    if "replacements" in recorded:
        state["replacements"] = recorded["replacements"]
    manifest.write_text(json.dumps(state))


@pytest.mark.parametrize("refresh_manifest", [False, True])
def test_changed_content_without_version_is_rejected(version_repo, refresh_manifest):
    root, module = version_repo
    hints = root / "backend/experiment_packages/sht31_temperature_humidity/teaching/hints.yaml"
    hints.write_text(hints.read_text().replace("先", "请先", 1))
    if refresh_manifest:
        update_manifest(root, module)
    with pytest.raises(ValueError, match="manifest|version increase"):
        module.check(root, "HEAD")


@pytest.mark.parametrize(
    "filename", ["README.md", "docs/project-truth-status.md", "docs/implementation-status.md"]
)
def test_stale_current_documentation_is_rejected(version_repo, filename):
    root, module = version_repo
    target = root / filename
    current = module.package_state(root / "backend/experiment_packages/sht31_temperature_humidity")[
        "version"
    ]
    target.write_text(target.read_text().replace(current, "0.0.0"))
    with pytest.raises(ValueError, match="documentation version mismatch"):
        module.check(root, "HEAD")


def test_valid_bump_and_historical_document_preservation(version_repo):
    root, module = version_repo
    module.check(root, "HEAD")
    metadata = root / "backend/experiment_packages/sht31_temperature_humidity/metadata.yaml"
    old_version = module.package_state(metadata.parent)["version"]
    major, minor, patch = (int(part) for part in old_version.split("."))
    new_version = f"{major}.{minor}.{patch + 1}"
    metadata.write_text(metadata.read_text().replace(old_version, new_version))
    update_manifest(root, module)
    for filename in module.DOC_VERSIONS:
        path = root / filename
        path.write_text(path.read_text().replace(old_version, new_version))
    (root / "docs/historical-report.md").write_text("Historical package version 0.0.0")
    module.check(root, "HEAD")
    with pytest.raises(ValueError, match="baseline unavailable"):
        module.check(root, "nonexistent-baseline")


def test_direct_package_replacement_requires_explicit_baseline_pair(version_repo):
    root, module = version_repo
    packages = root / "backend/experiment_packages"
    current = packages / "sht31_temperature_humidity"
    retired = packages / "retired_sensor_fixture"
    current.rename(retired)
    for path in retired.rglob("*.yaml"):
        path.write_text(path.read_text().replace("sht31_temperature_humidity", retired.name))
    update_manifest(root, module)
    subprocess.run(["git", "-C", str(root), "add", "."], check=True, capture_output=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(root),
            "-c",
            "user.name=Test",
            "-c",
            "user.email=test@example.invalid",
            "-c",
            "commit.gpgsign=false",
            "-c",
            "core.hooksPath=/dev/null",
            "commit",
            "-qm",
            "isolated retired package baseline",
        ],
        check=True,
        capture_output=True,
    )
    retired.rename(current)
    for path in current.rglob("*.yaml"):
        path.write_text(path.read_text().replace(retired.name, current.name))
    update_manifest(root, module)
    manifest = root / "scripts/package_versions.json"
    recorded = json.loads(manifest.read_text())
    recorded["replacements"] = {}
    manifest.write_text(json.dumps(recorded))
    with pytest.raises(ValueError, match="package removal"):
        module.check(root, "HEAD")
    recorded["replacements"] = {retired.name: current.name}
    manifest.write_text(json.dumps(recorded))
    module.check(root, "HEAD")
    readme = root / "README.md"
    readme.write_text(readme.read_text().replace("SHT31 温湿度 `1.0.0`", "SHT31 温湿度 `0.0.0`"))
    with pytest.raises(ValueError, match="documentation version mismatch"):
        module.check(root, "HEAD")


@pytest.mark.parametrize("replacements", [
    {"gpio_led_output": "sht31_temperature_humidity"},  # old still present
    {"retired": "missing"},  # replacement absent
    {"retired": "sht31_temperature_humidity", "another": "sht31_temperature_humidity"},
    {"retired": 1},
    ["retired=sht31_temperature_humidity"],
])
def test_invalid_repository_replacement_records_are_rejected(version_repo, replacements):
    root, module = version_repo
    manifest = root / "scripts/package_versions.json"
    recorded = json.loads(manifest.read_text())
    recorded["replacements"] = replacements
    manifest.write_text(json.dumps(recorded))
    with pytest.raises(ValueError, match="replacement"):
        module.check(root, "HEAD")


def test_reviewed_replacement_does_not_authorize_unrelated_removal(version_repo):
    root, module = version_repo
    shutil.rmtree(root / "backend/experiment_packages/gpio_led_output")
    update_manifest(root, module)
    with pytest.raises(ValueError, match="package removal"):
        module.check(root, "HEAD")
