"""Create Phase 6 student diagnosis feedback.

Revision ID: 20260720_0004
Revises: 20260720_0003
Create Date: 2026-07-20
"""

from collections.abc import Sequence
from typing import Optional, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20260720_0004"
down_revision: Optional[str] = "20260720_0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "diagnosis_feedback",
        sa.Column("device_id", sa.String(length=36), nullable=False),
        sa.Column("diagnosis_result_id", sa.String(length=36), nullable=False),
        sa.Column("action", sa.String(length=30), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("is_test_data", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.ForeignKeyConstraint(["device_id"], ["devices.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["diagnosis_result_id"], ["diagnosis_results.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_feedback_device_created",
        "diagnosis_feedback",
        ["device_id", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_feedback_device_created", table_name="diagnosis_feedback")
    op.drop_table("diagnosis_feedback")
