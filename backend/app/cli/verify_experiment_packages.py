from __future__ import annotations

import json

from app.experiment_packages.loader import load_experiment_packages


def main() -> None:
    packages = load_experiment_packages()
    print(
        json.dumps(
            [
                {
                    "experiment": bundle.metadata.experiment.code,
                    "version": bundle.metadata.package.version,
                    "package_hash": report.package_hash,
                    "checks": len(report.checks),
                    "valid": report.valid,
                }
                for bundle, report in packages
            ],
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
