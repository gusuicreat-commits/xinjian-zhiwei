#!/usr/bin/env sh
set -eu

backend_python=${BACKEND_PYTHON:-backend/.venv/bin/python}
backend_bin=$(dirname "$backend_python")

if [ ! -x "$backend_python" ]; then
  echo "backend Python not found: $backend_python" >&2
  exit 1
fi
if ! "$backend_python" -c 'import sys; raise SystemExit(sys.version_info < (3, 10))'; then
  echo "backend Python 3.10+ is required; recreate backend/.venv or set BACKEND_PYTHON" >&2
  exit 1
fi

"$backend_bin/ruff" check backend simulator
PYTHONPATH=backend "$backend_bin/pytest" backend/tests
simulator/.venv/bin/pytest simulator/tests
PYTHONPATH=backend "$backend_python" -m app.cli.run_synthetic_evaluation >/dev/null
"$backend_python" scripts/check_version.py
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
