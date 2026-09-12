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

backend_python=$("$backend_python" -c 'import sys; print(sys.executable)')
export BACKEND_PYTHON="$backend_python"
workflow_report=${WORKFLOW_EVALUATION_REPORT:-output/workflow-evaluation/local-postgres.json}

if [ -z "${XINJIAN_EVAL_POSTGRES_DSN:-}" ]; then
  echo "Full verification requires XINJIAN_EVAL_POSTGRES_DSN for an isolated test PostgreSQL database." >&2
  echo "DATABASE_URL is intentionally not used as a fallback. The blocked report records this missing gate." >&2
  PYTHONPATH=backend "$backend_python" -m app.cli.run_workflow_evaluation \
    --postgres --output "$workflow_report"
  exit 2
fi
# The explicitly selected test database can also host the checkpoint durability test.
TEST_DIAGNOSIS_CHECKPOINT_DSN=${TEST_DIAGNOSIS_CHECKPOINT_DSN:-$XINJIAN_EVAL_POSTGRES_DSN}
export TEST_DIAGNOSIS_CHECKPOINT_DSN

"$backend_python" scripts/prepare_evaluation_postgres.py
"$backend_bin/ruff" check backend simulator scripts/prepare_evaluation_postgres.py
PYTHONPATH=backend "$backend_bin/pytest" backend/tests
simulator/.venv/bin/pytest simulator/tests
PYTHONPATH=backend "$backend_python" -m app.cli.run_synthetic_evaluation >/dev/null
PYTHONPATH=backend "$backend_python" -m app.cli.verify_experiment_packages
PYTHONPATH=backend "$backend_python" -m app.cli.verify_structured_knowledge
PYTHONPATH=backend "$backend_python" -m app.cli.verify_v2_evidence_workflow
PYTHONPATH=backend "$backend_python" -m app.cli.run_workflow_evaluation \
  --postgres --output "$workflow_report"
"$backend_python" scripts/check_version.py
scripts/security_scan.sh

(
  cd frontend
  npm run lint
  npm run type-check
  npm run test -- --run
  npm run build
  npm run test:e2e
  npm run test:e2e:integration
)

if [ "${1:-}" = "--docker" ]; then
  docker compose build
  docker compose up -d
  docker compose ps
fi

echo "local verification passed"
