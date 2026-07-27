"""teacher intervention workflow and classroom messages

Revision ID: 20260727_0013
Revises: 20260727_0012
"""

import sqlalchemy as sa
from alembic import op

revision = "20260727_0013"
down_revision = "20260727_0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "intervention_cases",
        sa.Column(
            "diagnosis_result_id",
            sa.String(36),
            sa.ForeignKey("diagnosis_results.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "class_id",
            sa.String(36),
            sa.ForeignKey("classes.id", ondelete="SET NULL"),
        ),
        sa.Column(
            "assigned_teacher_user_id",
            sa.String(36),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
        ),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("version_no", sa.Integer(), nullable=False),
        sa.Column("resolution_summary", sa.Text()),
        sa.Column("is_test_data", sa.Boolean(), nullable=False),
        sa.Column("id", sa.String(36), primary_key=True),
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
        sa.UniqueConstraint(
            "diagnosis_result_id",
            name="uq_intervention_case_diagnosis",
        ),
    )
    op.create_index("ix_intervention_cases_class_id", "intervention_cases", ["class_id"])
    op.create_table(
        "intervention_events",
        sa.Column(
            "case_id",
            sa.String(36),
            sa.ForeignKey("intervention_cases.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "actor_user_id",
            sa.String(36),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("action", sa.String(30), nullable=False),
        sa.Column("from_status", sa.String(30)),
        sa.Column("to_status", sa.String(30)),
        sa.Column("note", sa.Text()),
        sa.Column("is_private", sa.Boolean(), nullable=False),
        sa.Column("metadata", sa.JSON(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("id", sa.String(36), primary_key=True),
    )
    op.create_index("ix_intervention_events_case_id", "intervention_events", ["case_id"])
    op.create_table(
        "classroom_messages",
        sa.Column(
            "class_id",
            sa.String(36),
            sa.ForeignKey("classes.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "author_user_id",
            sa.String(36),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("audience", sa.String(30), nullable=False),
        sa.Column("retracted_at", sa.DateTime(timezone=True)),
        sa.Column(
            "retracted_by_user_id",
            sa.String(36),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
        ),
        sa.Column("is_test_data", sa.Boolean(), nullable=False),
        sa.Column("id", sa.String(36), primary_key=True),
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
    )
    op.create_index("ix_classroom_messages_class_id", "classroom_messages", ["class_id"])


def downgrade() -> None:
    op.drop_table("classroom_messages")
    op.drop_table("intervention_events")
    op.drop_table("intervention_cases")
