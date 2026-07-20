"""Create Phase 4 deterministic diagnosis results.

Revision ID: 20260720_0002
Revises: 20260719_0001
Create Date: 2026-07-20
"""

from collections.abc import Sequence
from typing import Optional, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20260720_0002"
down_revision: Optional[str] = "20260719_0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "diagnosis_results",
        sa.Column("device_id", sa.String(length=36), nullable=False),
        sa.Column("evaluated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ruleset_version", sa.String(length=100), nullable=False),
        sa.Column("ruleset_hash", sa.String(length=64), nullable=False),
        sa.Column("input_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("matched_rules", sa.JSON(), nullable=False),
        sa.Column("evidence", sa.JSON(), nullable=False),
        sa.Column("context_snapshot", sa.JSON(), nullable=False),
        sa.Column("is_test_data", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.ForeignKeyConstraint(["device_id"], ["devices.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_diagnosis_results_device_created",
        "diagnosis_results",
        ["device_id", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_diagnosis_results_input_fingerprint",
        "diagnosis_results",
        ["input_fingerprint"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_diagnosis_results_input_fingerprint", table_name="diagnosis_results")
    op.drop_index("ix_diagnosis_results_device_created", table_name="diagnosis_results")
    op.drop_table("diagnosis_results")
