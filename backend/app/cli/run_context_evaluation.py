"""Exit 0 means software fixtures passed, never semantic or hardware acceptance."""

import argparse
from pathlib import Path

from app.evaluation.context_runner import (
    EXPECTATIONS,
    INPUTS,
    context_exit_code,
    run_context_evaluation,
    write_context_report,
)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inputs", type=Path, default=INPUTS)
    parser.add_argument("--expectations", type=Path, default=EXPECTATIONS)
    parser.add_argument(
        "--output", type=Path, default=Path("output/context-evaluation/latest.json")
    )
    args = parser.parse_args()
    report = run_context_evaluation(args.inputs, args.expectations)
    write_context_report(report, args.output)
    print(f"context-evaluation-v1: {report['status']}; semantic_review=not_run; {args.output}")
    raise SystemExit(context_exit_code(report))


if __name__ == "__main__":
    main()
