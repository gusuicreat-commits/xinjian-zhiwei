"""Seed an explicitly prefixed, fully synthetic demo classroom."""

import argparse
import secrets

from sqlalchemy import select

from app.core.security import hash_device_token, hash_password
from app.db.session import SessionLocal
from app.models import Classroom, Course, Device, DeviceBinding, User
from app.models.classroom import Enrollment, TeachingAssignment
from app.services.rbac import assign_role, ensure_rbac_catalog


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--prefix", default="demo-")
    args = parser.parse_args()
    if not args.prefix.startswith("demo-") or len(args.prefix) > 30:
        raise SystemExit("prefix must start with demo- and contain at most 30 characters")
    device_key = f"{args.prefix}device"
    with SessionLocal() as db:
        if db.scalar(select(Device).where(Device.device_key == device_key)) is not None:
            raise SystemExit("demo prefix already exists; reset it explicitly before reseeding")
        device_token = secrets.token_urlsafe(32)
        student_password = secrets.token_urlsafe(18)
        teacher_password = secrets.token_urlsafe(18)
        student = User(
            username=f"{args.prefix}student",
            display_name="合成演示学生",
            password_hash=hash_password(student_password),
            is_test_data=True,
        )
        teacher = User(
            username=f"{args.prefix}teacher",
            display_name="合成演示教师",
            password_hash=hash_password(teacher_password),
            is_test_data=True,
        )
        roles = ensure_rbac_catalog(db)
        course = Course(
            code=f"{args.prefix}course",
            title="合成演示课程",
            is_test_data=True,
        )
        device = Device(
            device_key=device_key,
            display_name="合成演示设备",
            device_type="synthetic-demo",
            token_hash=hash_device_token(device_token),
            metadata_json={"demo_prefix": args.prefix, "is_test_data": True},
        )
        db.add_all([student, teacher, course, device])
        db.flush()
        classroom = Classroom(
            course_id=course.id,
            code=f"{args.prefix}class",
            name="合成演示班级",
            term="synthetic-demo",
            is_test_data=True,
        )
        db.add(classroom)
        db.flush()
        assign_role(db, student, roles["student"])
        assign_role(db, teacher, roles["teacher"])
        db.add(Enrollment(class_id=classroom.id, user_id=student.id, status="active"))
        db.add(TeachingAssignment(class_id=classroom.id, user_id=teacher.id))
        db.add(
            DeviceBinding(
                device_id=device.id,
                class_id=classroom.id,
                student_user_id=student.id,
                is_active=True,
            )
        )
        db.commit()
    print(f"prefix={args.prefix}")
    print(f"student_page_device_id={device_key}")
    print(f"student_page_device_token={device_token}")
    print(f"rbac_student_username={args.prefix}student")
    print(f"rbac_student_password={student_password}")
    print(f"teacher_page_username={args.prefix}teacher")
    print(f"teacher_page_password={teacher_password}")
    print(
        "The current student page uses the device pair; the RBAC student pair "
        "is reserved for scoped classroom APIs."
    )
    print("All credentials above are synthetic, shown once, and were not written to Git.")


if __name__ == "__main__":
    main()
