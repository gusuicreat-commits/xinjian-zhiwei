#!/usr/bin/env sh
set -eu

backend/.venv/bin/ruff check backend simulator
backend/.venv/bin/pytest backend/tests
simulator/.venv/bin/pytest simulator/tests
PYTHONPATH=backend backend/.venv/bin/python -m app.cli.run_synthetic_evaluation >/dev/null
backend/.venv/bin/python scripts/check_version.py
scripts/security_scan.sh

(
  cd frontend
  npm run lint
  npm run type-check
  npm run test -- --run
  npm run build
  npm run test:e2e
)

if [ "${1:-}" = "--docker" ]; then
  docker compose build
  docker compose up -d
  docker compose ps
fi

echo "local verification passed"
