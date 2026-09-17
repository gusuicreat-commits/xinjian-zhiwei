"""Report size must not change verdicts or discard failure evidence."""

import copy
import gzip
import json

import pytest

from app.evaluation.reporting import write_workflow_report


def report(status="failed"):
    return {
        "status": status,
        "cases": [
            {
                "id": "ok",
                "status": "passed",
                "checks": [
                    {"requirement": "evidence", "status": "passed", "actual": ["large"] * 1000}
                ],
                "snapshots": [{"payload": ["repeated"] * 1000}],
            },
            {
                "id": "bad",
                "status": status,
                "checks": [
                    {
                        "requirement": "foreign_evidence",
                        "status": status,
                        "expected": ["own-id"],
                        "actual": ["foreign-id"],
                    }
                ],
                "snapshots": [{"evidence_id": "foreign-id"}],
            },
        ],
        "code_hashes": {"source.py": "fingerprint"},
        "semantic_review": "not_run",
        "hardware_validation": "not_run",
        "is_test_data": True,
    }


def test_compact_report_preserves_verdict_and_failure_evidence(tmp_path):
    raw = report()
    before = copy.deepcopy(raw)
    output = tmp_path / "report.json"
    summary = write_workflow_report(raw, output)
    compact = json.loads(output.read_text())
    assert raw == before  # Reporting never changes test outcomes.
    assert compact["status"] == "failed"
    assert compact["cases"][1]["failed_requirements"] == ["foreign_evidence"]
    assert compact["code_hashes"] == raw["code_hashes"]
    assert compact["semantic_review"] == "not_run"
    assert "snapshots" not in compact["cases"][0]
    with gzip.open(tmp_path / compact["detail_artifact"], "rt") as handle:
        details = json.load(handle)
    assert details["cases"] == [raw["cases"][1]]
    assert "foreign_evidence" in summary.read_text()
    assert len(summary.read_text().splitlines()) < 25
    assert output.stat().st_size < len(json.dumps(raw).encode()) / 5


def test_success_overwrites_summary_and_removes_only_its_stale_attachment(tmp_path):
    output = tmp_path / "report.json"
    write_workflow_report(report(), output)
    unrelated = tmp_path / "other.details.json.gz"
    unrelated.write_bytes(b"keep")
    write_workflow_report(report("passed"), output)
    compact = json.loads(output.read_text())
    assert compact["status"] == "passed" and compact["detail_artifact"] is None
    assert not (tmp_path / "report.details.json.gz").exists()
    assert unrelated.read_bytes() == b"keep"


@pytest.mark.parametrize("mode,count", [("all", 2), ("none", 0)])
def test_explicit_detail_modes(tmp_path, mode, count):
    output = tmp_path / "report.json"
    write_workflow_report(report(), output, details=mode)
    compact = json.loads(output.read_text())
    assert compact["status"] == "failed"
    if count:
        with gzip.open(tmp_path / compact["detail_artifact"], "rt") as handle:
            assert len(json.load(handle)["cases"]) == count
    else:
        assert compact["detail_artifact"] is None
        assert compact["cases"][1]["failed_requirements"] == ["foreign_evidence"]


@pytest.mark.parametrize("status,exit_code", [("passed", 0), ("failed", 1), ("incomplete", 2)])
def test_cli_exit_code_survives_report_compaction(tmp_path, monkeypatch, status, exit_code):
    import sys

    from app.cli.run_workflow_evaluation import main
    from app.evaluation import workflow_runner

    raw = report(status)
    monkeypatch.setattr(workflow_runner, "run_workflow_evaluation", lambda **_: raw)
    output = tmp_path / "report.json"
    monkeypatch.setattr(sys, "argv", ["test", "--output", str(output)])
    assert main() == exit_code
    assert json.loads(output.read_text())["status"] == status
    assert output.with_suffix(".md").exists()
