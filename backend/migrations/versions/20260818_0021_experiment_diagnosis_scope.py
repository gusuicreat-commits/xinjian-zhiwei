"""persist experiment identity and knowledge scope on diagnosis results

Revision ID: 20260818_0021
Revises: 20260813_0020
Create Date: 2026-08-18
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260818_0021"
down_revision: str | None = "20260813_0020"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "diagnosis_results", sa.Column("experiment_id", sa.String(length=100), nullable=True)
    )
    op.add_column(
        "diagnosis_results",
        sa.Column("experiment_version", sa.String(length=50), nullable=True),
    )
    op.add_column(
        "diagnosis_results",
        sa.Column("experiment_definition_hash", sa.String(length=64), nullable=True),
    )
    op.add_column("diagnosis_results", sa.Column("knowledge_scope", sa.JSON(), nullable=True))
    op.create_index(
        "ix_diagnosis_results_experiment_id",
        "diagnosis_results",
        ["experiment_id"],
        unique=False,
    )
    op.add_column(
        "guidance_history",
        sa.Column("fault_tree_source_id", sa.String(length=200), nullable=True),
    )
    op.add_column("guidance_history", sa.Column("fault_tree_scope", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("guidance_history", "fault_tree_scope")
    op.drop_column("guidance_history", "fault_tree_source_id")
    op.drop_index("ix_diagnosis_results_experiment_id", table_name="diagnosis_results")
    op.drop_column("diagnosis_results", "knowledge_scope")
    op.drop_column("diagnosis_results", "experiment_definition_hash")
    op.drop_column("diagnosis_results", "experiment_version")
    op.drop_column("diagnosis_results", "experiment_id")
