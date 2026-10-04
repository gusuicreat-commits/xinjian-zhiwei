"""Offline context analysis; --strict requires independent expectations to pass."""

import argparse
import json
from pathlib import Path

from app.experiment_packages.context_preview import (
    INPUTS,
    preview_exit_code,
    run_package_context_preview,
    write_preview_report,
)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package", type=Path, help="Optional explicit package directory")
    parser.add_argument("--inputs", type=Path, default=INPUTS)
    parser.add_argument(
        "--budgets", type=Path, help="JSON object containing allowed numeric budgets"
    )
    parser.add_argument(
        "--profile", type=Path,
        help="Explicit non-secret package-context-profile-v1 JSON; conflicting fixtures fail",
    )
    parser.add_argument(
        "--trusted-sources", type=Path, help="Explicit trusted snapshot mapping JSON"
    )
    parser.add_argument("--expectations", type=Path)
    parser.add_argument("--strict", action="store_true")
    parser.add_argument(
        "--output", type=Path, default=Path("output/package-context-preview/latest.json")
    )
    args = parser.parse_args()
    materials = {}
    try:
        for name, path in (
            ("budgets", args.budgets), ("trusted_sources", args.trusted_sources),
            ("profile", args.profile),
        ):
            if path is not None:
                if not path.is_file():
                    print("package-context-preview-v1: required material missing")
                    return 2
                materials[name] = json.loads(path.read_text())
        report = run_package_context_preview(
            args.inputs,
            package=args.package,
            expectations=args.expectations,
            strict=args.strict,
            **materials,
        )
        write_preview_report(report, args.output)
    except (OSError, ValueError, TypeError):
        print("package-context-preview-v1: invalid input or output material")
        return 1
    print(f"package-context-preview-v1: {report['status']}; provider=not_run; {args.output}")
    return preview_exit_code(report)


if __name__ == "__main__":
    raise SystemExit(main())
