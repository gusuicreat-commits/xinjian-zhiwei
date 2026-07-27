"""Run the synthetic diagnosis/retrieval baseline without modifying the database."""

import json

from app.evaluation.runner import run_evaluation


def main() -> None:
    report = run_evaluation()
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if not report["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
