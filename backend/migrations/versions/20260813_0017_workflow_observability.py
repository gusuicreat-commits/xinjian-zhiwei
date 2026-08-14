"""add bounded diagnosis workflow observability

Revision ID: 20260813_0017
Revises: 20260813_0016
Create Date: 2026-08-13
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260813_0017"
down_revision: str | None = "20260813_0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "diagnosis_workflow_runs",
        sa.Column("node_metrics", sa.JSON(), nullable=False, server_default="[]"),
    )
    op.add_column(
        "diagnosis_workflow_runs",
        sa.Column("retrieval_audit", sa.JSON(), nullable=False, server_default="{}"),
    )
    op.add_column(
        "diagnosis_workflow_runs",
        sa.Column("resume_count", sa.Integer(), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.drop_column("diagnosis_workflow_runs", "resume_count")
    op.drop_column("diagnosis_workflow_runs", "retrieval_audit")
    op.drop_column("diagnosis_workflow_runs", "node_metrics")
