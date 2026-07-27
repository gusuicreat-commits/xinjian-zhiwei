"""Create one explicitly marked test account; never stores a plaintext password."""

import argparse
import getpass

from sqlalchemy import select

from app.core.security import hash_password
from app.db.session import SessionLocal
from app.models.classroom import User
from app.services.rbac import ROLE_PERMISSIONS, assign_role, ensure_rbac_catalog


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--username", required=True)
    parser.add_argument("--display-name", required=True)
    parser.add_argument("--role", choices=sorted(ROLE_PERMISSIONS), required=True)
    parser.add_argument(
        "--test-account",
        action="store_true",
        required=True,
        help="Required acknowledgement that this is not a real user",
    )
    return parser


def main() -> None:
    args = _parser().parse_args()
    password = getpass.getpass("Test account password: ")
    confirmation = getpass.getpass("Repeat password: ")
    if password != confirmation or len(password) < 12:
        raise SystemExit("passwords must match and contain at least 12 characters")
    with SessionLocal() as db:
        if db.scalar(select(User).where(User.username == args.username)) is not None:
            raise SystemExit("username already exists")
        roles = ensure_rbac_catalog(db)
        user = User(
            username=args.username,
            display_name=args.display_name,
            password_hash=hash_password(password),
            is_active=True,
            is_test_data=True,
        )
        db.add(user)
        db.flush()
        assign_role(db, user, roles[args.role])
        db.commit()
    print(f"created explicit test account username={args.username} role={args.role}")


if __name__ == "__main__":
    main()
