"""XJ-009: exact, downward-only baseline for hand-built pipeline rows.

Do not raise or add allowlist counts to make a failure pass. New fixtures must use
pipeline.py; removing a legacy constructor requires lowering its frozen allowance.
This gate covers direct calls (including imported/assigned aliases and qualified
names), not arbitrary dynamic reflection or mutations of already-persisted rows.
"""

import ast
import json
from collections import Counter
from pathlib import Path

import pytest

MODELS = frozenset(
    {
        "DiagnosisResult",
        "DiagnosisEvidence",
        "DeviceLog",
        "SensorReading",
        "DeviceHeartbeat",
    }
)
TEST_ROOT = Path(__file__).resolve().parent
ALLOWLIST = TEST_ROOT / "handbuilt_rows_allowlist.json"


def constructor_counts(source):
    tree = ast.parse(source)
    names = {name: {name} for name in MODELS}
    # Handle `from app.models... import DiagnosisEvidence as Evidence`.
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and (node.module or "").startswith("app.models"):
            for alias in node.names:
                if alias.name in MODELS:
                    names[alias.asname or alias.name] = {alias.name}

    def model_for(node):
        if isinstance(node, ast.Name):
            return names.get(node.id, set())
        if isinstance(node, ast.Attribute) and node.attr in MODELS:
            return {node.attr}
        return set()

    # Simple constructor aliases such as `Row = models.DeviceLog` are still direct.
    assignments = [n for n in ast.walk(tree) if isinstance(n, (ast.Assign, ast.AnnAssign))]
    changed = True
    while changed:
        changed = False
        for node in assignments:
            model = model_for(node.value)
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for target in targets:
                if model and isinstance(target, ast.Name):
                    previous = names.get(target.id, set())
                    if not model <= previous:
                        names[target.id] = previous | model
                        changed = True
    return dict(
        Counter(
            model
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            for model in model_for(node.func)
        )
    )


def scan_constructors(root):
    counts = {}
    for path in sorted(root.rglob("*.py")):
        relative = path.relative_to(root).as_posix()
        if relative == "pipeline.py":
            continue
        models = constructor_counts(path.read_text(encoding="utf-8"))
        if models:
            counts[relative] = models
    return counts


def provenance_errors(actual, allowed):
    errors = []
    for filename in sorted(actual.keys() | allowed.keys()):
        observed, baseline = actual.get(filename, {}), allowed.get(filename, {})
        for model in sorted(observed.keys() | baseline.keys()):
            count, limit = observed.get(model, 0), baseline.get(model, 0)
            if count > limit:
                errors.append(
                    f"{filename}: {model} actual={count} allowlist={limit}; "
                    "新增手工构造流水线记录，请改用 tests/pipeline.py，禁止上调白名单"
                )
            elif count < limit:
                errors.append(
                    f"{filename}: {model} actual={count} allowlist={limit}; 请同步下调白名单"
                )
    return errors


def test_handbuilt_pipeline_rows_match_frozen_allowlist():
    document = json.loads(ALLOWLIST.read_text(encoding="utf-8"))
    allowed = document["files"]
    for filename, counts in allowed.items():
        assert filename != "pipeline.py" and filename.endswith(".py")
        assert counts and set(counts) <= MODELS
        assert all(type(count) is int and count > 0 for count in counts.values())
    errors = provenance_errors(scan_constructors(TEST_ROOT), allowed)
    assert not errors, "手工构造棘轮门禁失败：\n" + "\n".join(errors)


@pytest.mark.parametrize(
    "source, expected",
    [
        ("DiagnosisEvidence()", {"DiagnosisEvidence": 1}),
        ("db.add(DiagnosisResult())", {"DiagnosisResult": 1}),
        (
            "db.add_all([DeviceLog(), SensorReading(), DeviceHeartbeat()])",
            {"DeviceLog": 1, "SensorReading": 1, "DeviceHeartbeat": 1},
        ),
        (
            "from app.models.diagnosis import DiagnosisEvidence as Evidence\nEvidence()",
            {"DiagnosisEvidence": 1},
        ),
        ("import app.models as models\nmodels.DeviceLog()", {"DeviceLog": 1}),
        ("Row = models.SensorReading\nAlias = Row\nAlias()", {"SensorReading": 1}),
        ("Row = DeviceLog\nRow = SensorReading\nRow()", {"DeviceLog": 1, "SensorReading": 1}),
        ('# DiagnosisResult()\ntext = "DeviceLog()"\nselect(DiagnosisEvidence)', {}),
    ],
)
def test_scanner_counts_direct_constructors_and_aliases(source, expected):
    assert constructor_counts(source) == expected


def test_ratchet_rejects_additions_and_requires_baseline_reduction():
    assert provenance_errors({"new.py": {"DiagnosisEvidence": 1}}, {}) == [
        "new.py: DiagnosisEvidence actual=1 allowlist=0; "
        "新增手工构造流水线记录，请改用 tests/pipeline.py，禁止上调白名单"
    ]
    assert provenance_errors({}, {"old.py": {"DiagnosisResult": 1}}) == [
        "old.py: DiagnosisResult actual=0 allowlist=1; 请同步下调白名单"
    ]
    assert (
        provenance_errors(
            {"old.py": {"DiagnosisResult": 1}},
            {"old.py": {"DiagnosisResult": 1}},
        )
        == []
    )


def test_scanner_visits_nested_files_and_only_exempts_root_pipeline(tmp_path):
    (tmp_path / "pipeline.py").write_text("DiagnosisResult()", encoding="utf-8")
    nested = tmp_path / "nested"
    nested.mkdir()
    (nested / "pipeline.py").write_text("db.add(DeviceLog())", encoding="utf-8")
    assert scan_constructors(tmp_path) == {"nested/pipeline.py": {"DeviceLog": 1}}


@pytest.mark.parametrize("name", ["dht11_temperature_humidity", "gpio_led_output"])
def test_pipeline_preserves_ingested_reading_identity_and_package_semantics(api_context, name):
    """Independent protocol/package expectations for the reusable record factories."""
    from datetime import timedelta

    from pipeline import (
        dht11_reading,
        diagnose_session,
        heartbeat,
        ingest_batch,
        led_reading,
        publish_package,
    )
    from sqlalchemy import select

    from app.models import DeviceHeartbeat, DiagnosisEvidence, ExperimentSession, SensorReading
    from app.models.base import utc_now

    now = utc_now()
    if name == "dht11_temperature_humidity":
        records = [
            dht11_reading("temperature", 24, occurred_at=now),
            dht11_reading("humidity", 50, occurred_at=now),
        ]
        expected = {"observation.temperature", "observation.humidity"}
    else:
        records = [
            led_reading(metric, 1, source, occurred_at=now)
            for metric, source in (
                ("level", "unknown"),
                ("gpio_command_level", "command"),
                ("gpio_actual_level", "electrical_measurement"),
            )
        ]
        expected = {
            "observation.level",
            "observation.gpio_command_level",
            "observation.gpio_actual_level",
        }
    records.append(heartbeat(occurred_at=now))
    receipt = ingest_batch(
        api_context["client"],
        api_context["headers"],
        records,
        sent_at=now,
        firmware_version="0.2.5",
        uptime_ms=3000,
    )
    reading_ids = {r["id"] for r in receipt["records"] if r["type"] == "reading"}
    with api_context["session_factory"]() as db:
        session = db.get(ExperimentSession, api_context["experiment_session_id"])
        version = publish_package(db, name)
        session.experiment_version_id = version.id
        db.commit()
        diagnosis = diagnose_session(db, session, evaluated_at=now + timedelta(seconds=1))
        rows = list(
            db.scalars(
                select(DiagnosisEvidence).where(
                    DiagnosisEvidence.diagnosis_id == diagnosis.id,
                    DiagnosisEvidence.source_type == "sensor_reading",
                )
            )
        )
        assert {row.evidence_type for row in rows} == expected
        assert {row.source_ref for row in rows} == reading_ids
        assert all(row.experiment_version_id == version.id for row in rows)
        assert diagnosis.is_test_data and version.status == "published"
        assert db.scalar(select(DeviceHeartbeat)).firmware_version == "0.2.5"
        assert {r.id for r in db.scalars(select(SensorReading))} == reading_ids
        by_type = {row.evidence_type: row for row in rows}
        if name == "dht11_temperature_humidity":
            assert by_type["observation.temperature"].normalized_value["unit"] == "°C"
            assert by_type["observation.humidity"].normalized_value["unit"] == "%RH"
            assert all(
                row.raw_payload["metadata"]["measurement_semantics"] == "previous_conversion"
                for row in rows
            )
        else:
            assert by_type["observation.level"].normalized_value["status"] == "unknown"
            assert by_type["observation.gpio_command_level"].normalized_value["status"] == "normal"
            assert by_type["observation.gpio_actual_level"].normalized_value["status"] == "normal"
            assert "observation.led_physically_on" not in by_type
