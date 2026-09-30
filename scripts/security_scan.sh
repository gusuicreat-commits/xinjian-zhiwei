#!/usr/bin/env sh
set -eu

# verify.sh provides its tested Python; CI and direct invocations use python3.
scanner_python=${BACKEND_PYTHON:-python3}
scanner_dir=$(CDPATH='' cd -- "$(dirname -- "$0")" && pwd)
exec "$scanner_python" "$scanner_dir/security_scan.py"
