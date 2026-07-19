import argparse
import getpass
import os

from sqlalchemy import select

from app.core.security import hash_device_token
from app.db.session import SessionLocal
from app.models.device import Device


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Create a device with a hashed access token")
    parser.add_argument("--device-id", required=True, help="Stable external device identifier")
    parser.add_argument("--display-name", help="Optional human-readable label")
    parser.add_argument("--device-type", help="Optional generic device category")
    parser.add_argument(
        "--token-env",
        metavar="VARIABLE",
        help="Read the token from this environment variable instead of an interactive prompt",
    )
    return parser


def main() -> None:
    args = build_parser().parse_args()
    if args.token_env:
        token = os.environ.get(args.token_env, "")
    else:
        token = getpass.getpass("Device token: ")
        confirmation = getpass.getpass("Confirm device token: ")
        if token != confirmation:
            raise SystemExit("Tokens do not match")
    if not token:
        raise SystemExit("Token must not be empty")

    with SessionLocal() as db:
        if db.scalar(select(Device).where(Device.device_key == args.device_id)) is not None:
            raise SystemExit("Device ID already exists")
        device = Device(
            device_key=args.device_id,
            display_name=args.display_name,
            device_type=args.device_type,
            token_hash=hash_device_token(token),
        )
        db.add(device)
        db.commit()
        print(f"Created device {args.device_id}; token stored as a one-way hash.")


if __name__ == "__main__":
    main()
