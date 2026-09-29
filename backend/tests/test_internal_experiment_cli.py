"""The operator CLI never implicitly chooses the business database."""

import pytest

from app.cli.prepare_internal_experiment import build_parser, run
from app.services.internal_experiment_preparation import PreparationError


def args():
    return build_parser().parse_args(
        [
            "plan",
            "--test-database",
            "--dsn-env",
            "TEST_EXPLICIT_LAB_DSN",
            "--actor-token-env",
            "TEST_EXPLICIT_ACTOR",
            "--prefix",
            "lab-cli-test",
            "--package-version-id",
            "00000000-0000-0000-0000-000000000001",
            "--package-hash",
            "a" * 64,
        ]
    )


def test_cli_requires_test_environment_before_connecting(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    with pytest.raises(PreparationError, match="APP_ENV=test"):
        run(args())


def test_cli_does_not_fall_back_to_database_url(monkeypatch):
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("DATABASE_URL", "postgresql://should-never-be-used/business")
    monkeypatch.delenv("TEST_EXPLICIT_LAB_DSN", raising=False)
    with pytest.raises(PreparationError, match="explicit test DSN"):
        run(args())
