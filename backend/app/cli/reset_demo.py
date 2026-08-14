"""Delete only explicitly prefixed test demo objects."""

import argparse

from sqlalchemy import delete, select

from app.db.session import SessionLocal
from app.models import (
    Course,
    Device,
    DiagnosisWorkflowRun,
    ExperimentSession,
    Permission,
    Role,
    User,
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--prefix", required=True)
    parser.add_argument("--confirm", required=True)
    args = parser.parse_args()
    if not args.prefix.startswith("demo-") or args.confirm != args.prefix:
        raise SystemExit("prefix must start with demo- and --confirm must match exactly")
    with SessionLocal() as db:
        devices = list(
            db.scalars(
                select(Device).where(
                    Device.device_key.startswith(args.prefix),
                    Device.device_type == "synthetic-demo",
                )
            )
        )
        users = list(
            db.scalars(
                select(User).where(
                    User.username.startswith(args.prefix),
                    User.is_test_data.is_(True),
                )
            )
        )
        courses = list(
            db.scalars(
                select(Course).where(
                    Course.code.startswith(args.prefix),
                    Course.is_test_data.is_(True),
                )
            )
        )
        device_ids = [item.id for item in devices]
        if device_ids:
            db.execute(
                delete(DiagnosisWorkflowRun).where(DiagnosisWorkflowRun.device_id.in_(device_ids))
            )
            db.execute(delete(ExperimentSession).where(ExperimentSession.device_id.in_(device_ids)))
        for item in [*devices, *users, *courses]:
            db.delete(item)
        db.execute(delete(Role).where(Role.code.startswith(args.prefix)))
        db.execute(delete(Permission).where(Permission.code.startswith(args.prefix)))
        db.commit()
    print(
        f"reset prefix={args.prefix} devices={len(devices)} "
        f"users={len(users)} courses={len(courses)}"
    )


if __name__ == "__main__":
    main()
