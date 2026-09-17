"""Run code checks only; exit 0 does not mean the unrun semantic review passed."""

import json

from app.evaluation.runner import run_evaluation


def main() -> None:
    report = run_evaluation()
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if not report["code_checks_passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
