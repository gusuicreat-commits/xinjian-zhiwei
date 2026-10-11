"""Replacement records must authorize only the reviewed package transition."""

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "check_version", ROOT / "scripts/check_version.py"
)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


def check(old, current, replacements):
    MODULE.validate_package_replacements(set(old), set(current), replacements)


def test_replacement_passes_when_baseline_contains_old_package():
    check(
        {"dht11_temperature_humidity"},
        {"sht31_temperature_humidity"},
        {"dht11_temperature_humidity": "sht31_temperature_humidity"},
    )


def test_completed_replacement_record_passes_against_later_baseline():
    check(
        {"sht31_temperature_humidity"},
        {"sht31_temperature_humidity"},
        {"dht11_temperature_humidity": "sht31_temperature_humidity"},
    )


def test_old_baseline_package_requires_a_record():
    with pytest.raises(ValueError, match="package removal"):
        check({"dht11_temperature_humidity"}, {"sht31_temperature_humidity"}, {})


@pytest.mark.parametrize(
    "old, current, replacements",
    [
        (
            {"dht11_temperature_humidity"},
            {"other_sensor"},
            {"dht11_temperature_humidity": "sht31_temperature_humidity"},
        ),
        (
            {"dht11_temperature_humidity"},
            {"dht11_temperature_humidity", "sht31_temperature_humidity"},
            {"dht11_temperature_humidity": "sht31_temperature_humidity"},
        ),
    ],
)
def test_invalid_replacement_successor_or_old_package_is_rejected(
    old, current, replacements
):
    with pytest.raises(ValueError, match="package"):
        check(old, current, replacements)
