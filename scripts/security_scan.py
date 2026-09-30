"""High-confidence Git candidate scan; output contains locations, never file contents."""
from __future__ import annotations

import json
import os
import re
import stat
import subprocess
import sys
from pathlib import Path

RULES = (
    ('PRIVATE_KEY', re.compile(rb'BEGIN (RSA|OPENSSH|EC) PRIVATE KEY')),
    ('OPENAI_KEY', re.compile(rb'sk-[A-Za-z0-9]{20,}')),
    ('GOOGLE_KEY', re.compile(rb'AIza[0-9A-Za-z_-]{20,}')),
)
SENSITIVE = re.compile(
    r'(^|/)\.env$|(^|/)node_modules(/|$)|(^|/)data/postgres(/|$)|'
    r'(^|/)backups(/|$)|\.(dump|backup|bak)$'
)


def report(path: str, line: int | None, rule: str) -> None:
    # JSON escapes newlines, controls and invalid UTF-8 filename bytes.
    print(json.dumps({'path': path, 'line': line, 'rule': rule}, ensure_ascii=True))


def scan() -> int:
    try:
        result = subprocess.run(
            ['git', 'ls-files', '-z', '--cached', '--others', '--exclude-standard'],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, check=True,
        )
    except (OSError, subprocess.SubprocessError):
        print('security scan failed: GIT_CANDIDATES_UNAVAILABLE', file=sys.stderr)
        return 2
    found = False
    failed = False
    for raw_path in sorted(set(result.stdout.split(b'\0')) - {b''}):
        path = os.fsdecode(raw_path)
        if SENSITIVE.search(path):
            report(path, None, 'SENSITIVE_PATH')
            found = True
            continue
        try:
            candidate = Path(path)
            # Do not follow a link into an unrelated or private location.
            if not stat.S_ISREG(candidate.lstat().st_mode):
                report(path, None, 'FILE_NOT_REGULAR')
                failed = True
                continue
            with candidate.open('rb') as stream:
                for number, line in enumerate(stream, 1):
                    for rule, pattern in RULES:
                        if pattern.search(line):
                            report(path, number, rule)
                            found = True
        except OSError:
            report(path, None, 'FILE_UNREADABLE')
            failed = True
    if failed:
        print('security scan failed: CANDIDATE_READ_ERROR', file=sys.stderr)
        return 2
    if found:
        print('possible secret or sensitive path detected in Git candidates', file=sys.stderr)
        return 1
    print('Git candidate-path and high-confidence secret scan passed')
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(scan())
    except Exception:  # noqa: BLE001 - the log boundary must never expose exception contents
        # Never print arbitrary exception messages (which may contain file contents).
        print('security scan failed: INTERNAL_ERROR', file=sys.stderr)
        raise SystemExit(2) from None
