"""Offline HTTP/workflow evaluation; nonzero exit for failures or unexecuted cases."""

import argparse
import json
import os
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path, help="JSON report path")
    parser.add_argument(
        "--postgres", action="store_true", help="Use isolated schemas on XINJIAN_EVAL_POSTGRES_DSN"
    )
    args = parser.parse_args()
    dsn = os.getenv("XINJIAN_EVAL_POSTGRES_DSN") if args.postgres else None
    if args.postgres and not dsn:
        report = {
            "version": "workflow-evaluation-v2-remediation",
            "status": "blocked",
            "reason": "XINJIAN_EVAL_POSTGRES_DSN is not configured",
            "cases": [],
            "is_test_data": True,
        }
    else:
        from app.evaluation.workflow_runner import run_workflow_evaluation

        report = run_workflow_evaluation(postgres_dsn=dsn)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(
        json.dumps(
            {k: report[k] for k in ("status", "counts", "reason") if k in report},
            ensure_ascii=False,
        )
    )
    for case in report["cases"]:
        failed = [c["requirement"] for c in case["checks"] if c["status"] == "failed"]
        print(case["id"], case["status"], ", ".join(failed))
    return (
        0
        if report["status"] == "passed"
        else 2
        if report["status"] in {"blocked", "incomplete"}
        else 1
    )


if __name__ == "__main__":
    raise SystemExit(main())
