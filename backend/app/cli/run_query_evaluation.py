"""Default-offline isolated query evaluation; never reads production DATABASE_URL."""

import argparse
from pathlib import Path

from app.evaluation.query_runner import FIXTURES, evaluate, write_report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=["offline", "real"], default="offline")
    parser.add_argument("--split", choices=["all", "development", "holdout"], default="all")
    parser.add_argument("--fixtures", type=Path, default=FIXTURES)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--budget-record", type=Path)
    parser.add_argument("--state-dir", type=Path)
    parser.add_argument("--repeats", type=int, choices=[1, 2, 3], default=3)
    parser.add_argument("--max-pairs", type=int)
    args = parser.parse_args()
    if args.output.suffix != ".json":
        parser.error("--output must end in .json")
    if args.mode == "real":
        import json

        from app.core.config import get_settings
        from app.evaluation.query_real import (
            EvaluationBlocked,
            atomic_json,
            evaluate_real,
            markdown_report,
        )

        if args.budget_record is None or args.state_dir is None:
            parser.exit(
                2, "Real evaluation requires --budget-record and --state-dir; no request sent.\n"
            )
        try:
            budget = json.loads(args.budget_record.read_text())
            result = evaluate_real(
                args.state_dir,
                budget,
                get_settings(),
                fixtures=args.fixtures,
                repeats=args.repeats,
                split=args.split,
                max_pairs=args.max_pairs,
            )
        except (EvaluationBlocked, OSError, ValueError) as exc:
            parser.exit(
                2, f"Real evaluation blocked: {type(exc).__name__}; inspect retained receipts.\n"
            )
        args.output.parent.mkdir(parents=True, exist_ok=True)
        atomic_json(args.output, result)
        markdown_report(result, args.output.with_suffix(".md"))
        print(
            f"{len(result['pairs'])} pairs; "
            f"execution={result.get('execution_status', 'incomplete')}; "
            f"overall=incomplete; attempts={result.get('usage', {}).get('physical_attempts', 0)}"
        )
        return (
            0
            if result.get("execution_status") == "completed" and result.get("code_checks_passed")
            else 2
        )
    result = evaluate(args.fixtures, args.split)
    write_report(result, args.output)
    print(
        f"{len(result['cases'])} cases; code_checks_passed={result['code_checks_passed']}; "
        "overall=incomplete; real_provider_calls=0"
    )
    return 0 if result["code_checks_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
