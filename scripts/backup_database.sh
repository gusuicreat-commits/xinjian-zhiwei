#!/usr/bin/env sh
set -eu
script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
exec "${BACKEND_PYTHON:-python3}" "$script_dir/database_backup.py" backup "$@"
