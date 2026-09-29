"""Provision an explicitly selected internal test database, never publish a package."""

import argparse
import getpass
import json
import os
import sys

from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.services.auth import resolve_session
from app.services.internal_experiment_preparation import (
    PreparationError,
    PreparationSpec,
    apply_preparation,
    inspect_preparation,
)


def build_parser():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=["plan", "apply", "status"])
    parser.add_argument(
        "--test-database",
        action="store_true",
        required=True,
        help="Acknowledge an isolated internal test database, not the business database",
    )
    parser.add_argument(
        "--dsn-env",
        required=True,
        help="Name of environment variable containing test PostgreSQL DSN",
    )
    parser.add_argument(
        "--actor-token-env",
        required=True,
        help="Name of variable containing authenticated test-admin bearer token",
    )
    parser.add_argument("--prefix", required=True)
    parser.add_argument("--package-version-id", required=True)
    parser.add_argument("--package-hash", required=True)
    parser.add_argument("--device-kind", choices=["synthetic", "hardware"], default="synthetic")
    parser.add_argument("--student-password-env")
    parser.add_argument("--teacher-password-env")
    parser.add_argument("--device-token-env")
    return parser


def _secret(variable, label):
    if variable:
        value = os.environ.get(variable)
        if not value:
            raise PreparationError("required credential environment variable is empty: " + variable)
        return value
    first = getpass.getpass(label + ": ")
    if first != getpass.getpass("Repeat " + label + ": "):
        raise PreparationError("credential confirmation differs")
    return first


def run(args):
    if os.environ.get("APP_ENV") != "test":
        raise PreparationError("APP_ENV=test is required for internal preparation")
    dsn = os.environ.get(args.dsn_env)
    token = os.environ.get(args.actor_token_env)
    if not dsn or not token:
        raise PreparationError("explicit test DSN and authenticated operator token are required")
    url = make_url(dsn)
    if url.get_backend_name() != "postgresql":
        raise PreparationError("a PostgreSQL test database is required")
    spec = PreparationSpec(
        args.prefix, args.package_version_id, args.package_hash, args.device_kind
    )
    engine = create_engine(
        url.set(drivername="postgresql+psycopg"), connect_args={"connect_timeout": 5}
    )
    try:
        with Session(engine, autoflush=False, expire_on_commit=False) as db:
            actor = resolve_session(db, token)
            if actor is None:
                raise PreparationError("operator token is expired or revoked")
            actor_id = actor.id
            initial = inspect_preparation(db, actor_id, spec)
            db.rollback()  # never hold a package lock while asking for credentials
            if args.operation != "apply":
                return initial
            credentials = {}
            if initial["state"] == "absent":
                credentials = {
                    "student_password": _secret(
                        args.student_password_env, "New test student password"
                    ),
                    "teacher_password": _secret(
                        args.teacher_password_env, "New test teacher password"
                    ),
                    "device_token": _secret(args.device_token_env, "New test device token"),
                }

            def recheck():
                db.expire_all()
                current = resolve_session(db, token)
                if current is None or not current.is_active or current.id != actor_id:
                    raise PreparationError("operator token expired or was revoked while waiting")

            return apply_preparation(db, actor_id, spec, recheck_access=recheck, **credentials)
    finally:
        engine.dispose()


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        result = run(args)
    except SQLAlchemyError:
        print(
            "Database operation failed; credentials and SQL parameters are omitted.",
            file=sys.stderr,
        )
        return 1
    except (ValueError, OSError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
