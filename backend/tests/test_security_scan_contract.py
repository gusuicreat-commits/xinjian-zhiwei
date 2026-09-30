"""Exercise the public scanner in disposable Git repositories, never real secrets."""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
SCANNER = ROOT / 'scripts/security_scan.sh'


def scan(path):
    return subprocess.run(
        [str(SCANNER)], cwd=path, capture_output=True, text=True,
        env={**os.environ, 'BACKEND_PYTHON': sys.executable},
    )


@pytest.fixture
def repository(tmp_path):
    subprocess.run(['git', 'init', '-q', str(tmp_path)], check=True)
    return tmp_path


@pytest.mark.parametrize('prefix', ['sk-', 'AIza', '-----BEGIN ' + 'RSA PRIVATE KEY-----'])
def test_secret_never_leaves_scanner(repository, prefix):
    secret = prefix + 'FictitiousSecretValue12345678901234'
    name = '中文 space\nsecond.txt'
    (repository / name).write_text('ordinary\n' + secret + '\n')
    result = scan(repository)
    assert result.returncode == 1
    assert secret not in result.stdout + result.stderr
    records = [json.loads(line) for line in result.stdout.splitlines()]
    assert records[0]['path'] == name
    assert records[0]['line'] == 2
    assert set(records[0]) == {'path', 'line', 'rule'}


def test_clean_and_binary_files_pass(repository):
    (repository / 'notes.txt').write_text('ordinary text')
    (repository / 'binary.bin').write_bytes(b'\x00ordinary')
    assert scan(repository).returncode == 0


def test_git_failure_is_not_clean(tmp_path):
    result = scan(tmp_path)
    assert result.returncode == 2
    assert 'passed' not in result.stdout
    assert result.stderr.strip() == 'security scan failed: GIT_CANDIDATES_UNAVAILABLE'


def test_unreadable_candidate_is_not_clean(repository):
    # A tracked file absent on disk is a deterministic read failure on every UID.
    candidate = repository / 'missing.txt'
    candidate.write_text('ordinary')
    subprocess.run(['git', 'add', 'missing.txt'], cwd=repository, check=True)
    candidate.unlink()
    result = scan(repository)
    assert result.returncode == 2
    assert 'passed' not in result.stdout
    assert 'FILE_UNREADABLE' in result.stdout


def test_sensitive_path_rejected_without_reading(repository):
    (repository / '.env').write_text('PRIVATE-FAKE-CONTENT')
    result = scan(repository)
    assert result.returncode == 1
    assert 'PRIVATE-FAKE-CONTENT' not in result.stdout + result.stderr
    assert json.loads(result.stdout)['rule'] == 'SENSITIVE_PATH'


def test_symlink_does_not_read_outside_repository(repository, tmp_path_factory):
    outside = tmp_path_factory.mktemp('outside') / 'private'
    outside.write_text('sk-' + 'FictitiousSecretValue12345678901234')
    (repository / 'link').symlink_to(outside)
    result = scan(repository)
    assert result.returncode == 2
    assert 'FictitiousSecretValue' not in result.stdout + result.stderr


def test_compose_healthcheck_uses_readiness():
    compose = yaml.safe_load((ROOT / 'compose.yaml').read_text())
    assert '/api/v1/health/ready' in ' '.join(compose['services']['backend']['healthcheck']['test'])


def test_readiness_tracks_database_failure_and_recovery():
    from fastapi.testclient import TestClient

    from app.db.session import get_db
    from app.main import app

    class Database:
        available = True

        def execute(self, statement):
            assert str(statement) == 'SELECT 1'
            if not self.available:
                raise ConnectionError('fake-private-connection-content')

    database = Database()
    previous = dict(app.dependency_overrides)
    app.dependency_overrides[get_db] = lambda: database
    try:
        with TestClient(app) as client:
            assert client.get('/api/v1/health/ready').status_code == 200
            database.available = False
            unavailable = client.get('/api/v1/health/ready')
            assert unavailable.status_code == 503
            assert 'fake-private-connection-content' not in unavailable.text
            assert client.get('/api/v1/health/live').status_code == 200
            database.available = True
            assert client.get('/api/v1/health/ready').status_code == 200
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(previous)


def test_file_permission_error_is_sanitized(repository, monkeypatch, capsys):
    import importlib.util

    spec = importlib.util.spec_from_file_location('safe_scanner', ROOT / 'scripts/security_scan.py')
    scanner = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(scanner)
    (repository / 'locked.txt').write_text('ordinary')
    monkeypatch.chdir(repository)

    def refuse_open(*args, **kwargs):
        raise PermissionError('private-exception-text-must-not-escape')

    monkeypatch.setattr(Path, 'open', refuse_open)
    assert scanner.scan() == 2
    output = capsys.readouterr()
    assert 'private-exception-text' not in output.out + output.err
    assert json.loads(output.out)['rule'] == 'FILE_UNREADABLE'
