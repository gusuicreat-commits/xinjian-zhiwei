"""Independent software fixtures; expectations never cross the packing boundary."""

import json
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

from app.ai.context_builder import payload_digest, select_knowledge
from app.ai.context_contract import CONTEXT_CONTRACT_VERSION, CONTEXT_POLICY_VERSION
from app.ai.schemas import AIKnowledgeReference
from app.core.config import Settings
from app.knowledge.matcher import match_knowledge_case_definitions

ROOT = Path(__file__).resolve().parents[2]
INPUTS = ROOT / "evaluation/context_inputs.json"
EXPECTATIONS = ROOT / "evaluation/context_expectations.json"


def exercise_input(sample):
    """Input-only adapter: same matcher and whole-unit selector used by the services."""
    settings = Settings(_env_file=None, **sample.get("settings", {}))
    diagnosis = SimpleNamespace(**sample["diagnosis"])
    sources = [SimpleNamespace(**source) for source in sample["sources"]]
    matched = match_knowledge_case_definitions(
        diagnosis, [], sources, limit=settings.ai_knowledge_limit
    )
    references = [
        AIKnowledgeReference(
            chunk_id=item.case_id,
            case_id=item.case_id,
            source_key=item.source_ref,
            source_title=item.symptom,
            source_type="structured_case",
            source_uri=None,
            source_version=item.version,
            similarity=item.match_score,
            is_test_data=item.is_test_data,
            content=json.dumps(
                {
                    "caseId": item.case_id,
                    "experimentType": item.experiment_type,
                    "errorType": item.error_type,
                    "symptom": item.symptom,
                    "normalState": item.normal_state,
                    "evidence": item.evidence,
                    "possibleCauses": item.possible_causes,
                    "solutionSteps": item.solution_steps,
                    "teacherNotes": item.teacher_notes,
                    "rootCause": {"value": item.root_cause_value, "status": item.root_cause_status},
                },
                ensure_ascii=False,
            ),
        )
        for item in matched
    ]
    selected, omissions = select_knowledge(references, settings, set())
    return {
        "matched_ids": [item.case_id for item in matched],
        "selected_ids": [item.case_id for item in selected],
        "omission_counts": omissions,
        "payloads": {item.case_id: json.loads(item.content) for item in selected},
        "source_versions": {item.case_id: item.source_version for item in selected},
    }


def attribute_stage(sample, expected, actual):
    # Only offline, authorized complete fixtures permit source-absence classification.
    if not sample["sources"]:
        return "source_absent"
    if not expected["eligible_ids"]:
        reviewed = [
            source
            for source in sample["sources"]
            if source["review_status"] == "approved"
            and source["facts_locked"]
            and source["quality_check_passed"]
            and source["root_cause_status"] == "confirmed"
        ]
        return "source_inapplicable" if reviewed else "source_unreviewed"
    if set(expected["eligible_ids"]) - set(actual["matched_ids"]):
        return "matcher_missed"
    if set(actual["matched_ids"]) - set(actual["selected_ids"]):
        return "packing_omitted"
    return "provided_material_ready"


def run_context_evaluation(inputs=INPUTS, expectations=EXPECTATIONS):
    started = time.monotonic()
    report = {
        "report_format": "context-evaluation-v1",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "contract_version": CONTEXT_CONTRACT_VERSION,
        "policy_version": CONTEXT_POLICY_VERSION,
        "status": "blocked",
        "code_checks_passed": False,
        "cases": [],
        "scope": "synthetic matcher/packing software fixtures; service boundaries run in pytest",
        "semantic_review": {
            "status": "not_run",
            "passed": None,
            "rubrics": "backend/evaluation/semantic_rubrics.json",
            "reason": "无真实模型输出及独立人工审阅，不判定语义通过。",
        },
        "real_provider": {"status": "not_run", "calls": 0, "tokens": None, "cost": None},
        "hardware": {"status": "not_run", "passed": None},
        "holdout": {"status": "not_run", "reason": "当前样本为开发回归；独立真实验收集待提供。"},
    }
    try:
        samples = json.loads(Path(inputs).read_text())["cases"]
        expected = json.loads(Path(expectations).read_text())["cases"]
        if not samples or len({s["id"] for s in samples}) != len(samples):
            raise ValueError("invalid input inventory")
        if {s["id"] for s in samples} != set(expected):
            raise ValueError("incomplete expectation inventory")
        report["inputs_sha256"] = payload_digest(samples)
        report["expectations_sha256"] = payload_digest(expected)
    except (OSError, ValueError, KeyError, TypeError):
        report["blocked_reason"] = "CONTEXT_EVALUATION_MATERIALS_INVALID_OR_MISSING"
        return report
    source_paths = [
        Path(__file__),
        ROOT / "app/ai/context_builder.py",
        ROOT / "app/ai/context_contract.py",
        ROOT / "app/ai/context_sanitizer.py",
        ROOT / "app/knowledge/matcher.py",
    ]
    report["source_fingerprints"] = {
        str(path.relative_to(ROOT.parent)): payload_digest(path.read_text())
        for path in source_paths
    }
    report["git_commit"] = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
    ).strip()
    for sample in samples:
        oracle = expected[sample["id"]]
        try:
            actual = exercise_input(sample)
            attribution = attribute_stage(sample, oracle, actual)
            checks = {
                "matched_ids": actual["matched_ids"] == oracle["matched_ids"],
                "selected_ids": actual["selected_ids"] == oracle["selected_ids"],
                "forbidden_excluded": not set(oracle["forbidden_ids"])
                & set(actual["selected_ids"]),
                "omission_counts": actual["omission_counts"] == oracle["omission_counts"],
                "stage_attribution": attribution == oracle["attribution"],
            }
            for case_id, required in oracle.get("required_fields", {}).items():
                for key, value in required.items():
                    checks[f"field:{case_id}:{key}"] = (
                        actual["payloads"].get(case_id, {}).get(key) == value
                    )
            for case_id, version in oracle.get("source_versions", {}).items():
                checks[f"version:{case_id}"] = actual["source_versions"].get(case_id) == version
            report["cases"].append(
                {
                    "id": sample["id"],
                    "split": sample["split"],
                    "family": sample["family"],
                    "attribution": attribution,
                    "status": "passed" if all(checks.values()) else "failed",
                    "checks": checks,
                    "actual": actual,
                }
            )
        except Exception as exc:
            report["cases"].append(
                {"id": sample["id"], "status": "error", "error_type": type(exc).__name__}
            )
    report["code_checks_passed"] = all(case["status"] == "passed" for case in report["cases"])
    report["status"] = "passed" if report["code_checks_passed"] else "failed"
    report["elapsed_ms"] = round((time.monotonic() - started) * 1000)
    return report


def write_context_report(report, output):
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    lines = [
        "# 上下文软件评测",
        "",
        f"代码检查：{report['status']}。",
        "语义审阅、真实 Provider、硬件和独立保留集均未验收。",
        "",
        "| 场景 | 软件结果 | 归因 |",
        "| --- | --- | --- |",
    ]
    for case in report["cases"]:
        lines.append(f"| {case['id']} | {case['status']} | {case.get('attribution', 'error')} |")
    lines += ["", "完整断言、输入/源码指纹及未完成项目见同名 JSON。"]
    output.with_suffix(".md").write_text("\n".join(lines) + "\n")


def context_exit_code(report):
    return 2 if report["status"] == "blocked" else 0 if report["code_checks_passed"] else 1
