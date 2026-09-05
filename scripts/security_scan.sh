#!/usr/bin/env sh
set -eu

included=$(git ls-files --cached --others --exclude-standard)
if printf '%s\n' "$included" | grep -E \
  '(^|/)\.env$|node_modules|(^|/)data/postgres|(^|/)backups|.*\.(dump|backup|bak)$' \
  >/dev/null
then
  echo "sensitive or generated path would be included in Git" >&2
  exit 1
fi

if git ls-files -z --cached --others --exclude-standard \
  | xargs -0 grep -IEns \
    'BEGIN (RSA|OPENSSH|EC) PRIVATE KEY|sk-[A-Za-z0-9]{20,}|AIza[0-9A-Za-z_-]{20,}' \
  | grep -v -E '(^|/)\.env\.example:|simulator/\.env\.example:|scripts/security_scan\.sh:'
then
  echo "possible secret detected in a Git candidate file" >&2
  exit 1
fi

echo "Git candidate-path and high-confidence secret scan passed"
