"""Create Phase 5 guidance history.

Revision ID: 20260720_0003
Revises: 20260720_0002
Create Date: 2026-07-20
"""

from collections.abc import Sequence
from typing import Optional, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20260720_0003"
down_revision: Optional[str] = "20260720_0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "guidance_history",
        sa.Column("device_id", sa.String(length=36), nullable=False),
        sa.Column("diagnosis_result_id", sa.String(length=36), nullable=False),
        sa.Column("fault_tree_id", sa.String(length=100), nullable=False),
        sa.Column("fault_tree_title", sa.String(length=200), nullable=False),
        sa.Column("fault_tree_status", sa.String(length=20), nullable=False),
        sa.Column("fault_tree_version", sa.String(length=100), nullable=False),
        sa.Column("fault_tree_hash", sa.String(length=64), nullable=False),
        sa.Column("first_detected_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("failure_count", sa.Integer(), nullable=False),
        sa.Column("anomaly_duration_seconds", sa.Integer(), nullable=False),
        sa.Column("hint_level", sa.Integer(), nullable=False),
        sa.Column("teacher_intervention_required", sa.Boolean(), nullable=False),
        sa.Column("ranked_causes", sa.JSON(), nullable=False),
        sa.Column("hints", sa.JSON(), nullable=False),
        sa.Column("is_test_data", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.ForeignKeyConstraint(["device_id"], ["devices.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["diagnosis_result_id"], ["diagnosis_results.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "diagnosis_result_id", "fault_tree_id", name="uq_guidance_diagnosis_tree"
        ),
    )
    op.create_index(
        "ix_guidance_device_created",
        "guidance_history",
        ["device_id", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_guidance_intervention_created",
        "guidance_history",
        ["teacher_intervention_required", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_guidance_intervention_created", table_name="guidance_history")
    op.drop_index("ix_guidance_device_created", table_name="guidance_history")
    op.drop_table("guidance_history")
