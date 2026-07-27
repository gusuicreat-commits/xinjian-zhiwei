"""classroom identity and RBAC foundation

Revision ID: 20260727_0011
Revises: 20260727_0010
"""

import sqlalchemy as sa
from alembic import op

revision = "20260727_0011"
down_revision = "20260727_0010"
branch_labels = None
depends_on = None


def _identity_columns() -> list[sa.Column]:
    return [
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    ]


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("username", sa.String(100), nullable=False),
        sa.Column("display_name", sa.String(200), nullable=False),
        sa.Column("password_hash", sa.String(512), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("is_test_data", sa.Boolean(), nullable=False),
        *_identity_columns(),
    )
    op.create_index("ix_users_username", "users", ["username"], unique=True)
    op.create_table(
        "roles",
        sa.Column("code", sa.String(50), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        *_identity_columns(),
        sa.UniqueConstraint("code"),
    )
    op.create_table(
        "permissions",
        sa.Column("code", sa.String(100), nullable=False),
        sa.Column("description", sa.String(300), nullable=False),
        *_identity_columns(),
        sa.UniqueConstraint("code"),
    )
    op.create_table(
        "user_roles",
        sa.Column(
            "user_id",
            sa.String(36),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "role_id",
            sa.String(36),
            sa.ForeignKey("roles.id", ondelete="CASCADE"),
            primary_key=True,
        ),
    )
    op.create_table(
        "role_permissions",
        sa.Column(
            "role_id",
            sa.String(36),
            sa.ForeignKey("roles.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "permission_id",
            sa.String(36),
            sa.ForeignKey("permissions.id", ondelete="CASCADE"),
            primary_key=True,
        ),
    )
    op.create_table(
        "courses",
        sa.Column("code", sa.String(100), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("description", sa.String(1000)),
        sa.Column("is_test_data", sa.Boolean(), nullable=False),
        *_identity_columns(),
        sa.UniqueConstraint("code"),
    )
    op.create_table(
        "classes",
        sa.Column(
            "course_id",
            sa.String(36),
            sa.ForeignKey("courses.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("code", sa.String(100), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("term", sa.String(100)),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("is_test_data", sa.Boolean(), nullable=False),
        *_identity_columns(),
        sa.UniqueConstraint("course_id", "code", name="uq_classes_course_code"),
    )
    op.create_table(
        "enrollments",
        sa.Column(
            "class_id",
            sa.String(36),
            sa.ForeignKey("classes.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            sa.String(36),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("status", sa.String(30), nullable=False),
        *_identity_columns(),
        sa.UniqueConstraint("class_id", "user_id", name="uq_enrollments_class_user"),
    )
    op.create_table(
        "teaching_assignments",
        sa.Column(
            "class_id",
            sa.String(36),
            sa.ForeignKey("classes.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            sa.String(36),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        *_identity_columns(),
        sa.UniqueConstraint("class_id", "user_id", name="uq_teaching_class_user"),
    )
    op.create_table(
        "experiment_assignments",
        sa.Column(
            "class_id",
            sa.String(36),
            sa.ForeignKey("classes.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("template_version_id", sa.String(36)),
        sa.Column("starts_at", sa.DateTime(timezone=True)),
        sa.Column("due_at", sa.DateTime(timezone=True)),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("is_test_data", sa.Boolean(), nullable=False),
        *_identity_columns(),
    )
    op.create_table(
        "device_bindings",
        sa.Column(
            "device_id",
            sa.String(36),
            sa.ForeignKey("devices.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "class_id",
            sa.String(36),
            sa.ForeignKey("classes.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "student_user_id",
            sa.String(36),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
        ),
        sa.Column(
            "experiment_assignment_id",
            sa.String(36),
            sa.ForeignKey("experiment_assignments.id", ondelete="SET NULL"),
        ),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        *_identity_columns(),
        sa.UniqueConstraint(
            "device_id",
            "class_id",
            "student_user_id",
            name="uq_device_bindings_scope",
        ),
    )
    op.create_table(
        "audit_events",
        sa.Column(
            "actor_user_id",
            sa.String(36),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
        ),
        sa.Column("action", sa.String(100), nullable=False),
        sa.Column("resource_type", sa.String(100), nullable=False),
        sa.Column("resource_id", sa.String(36)),
        sa.Column("details", sa.JSON(), nullable=False),
        sa.Column("is_test_data", sa.Boolean(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("id", sa.String(36), primary_key=True),
    )
    op.create_index("ix_audit_events_actor_user_id", "audit_events", ["actor_user_id"])
    op.create_index("ix_audit_events_action", "audit_events", ["action"])
    op.create_table(
        "auth_sessions",
        sa.Column(
            "user_id",
            sa.String(36),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        *_identity_columns(),
        sa.UniqueConstraint("token_hash"),
    )
    op.create_index("ix_auth_sessions_user_id", "auth_sessions", ["user_id"])


def downgrade() -> None:
    for table_name in (
        "auth_sessions",
        "audit_events",
        "device_bindings",
        "experiment_assignments",
        "teaching_assignments",
        "enrollments",
        "classes",
        "courses",
        "role_permissions",
        "user_roles",
        "permissions",
        "roles",
        "users",
    ):
        op.drop_table(table_name)
