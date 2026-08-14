"""make workflow AI call persistence replay-safe

Revision ID: 20260813_0019
Revises: 20260813_0018
Create Date: 2026-08-13
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260813_0019"
down_revision: str | None = "20260813_0018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Batch operations preserve the same PostgreSQL DDL while keeping migration
    # smoke tests usable with SQLite's limited ALTER TABLE support.
    with op.batch_alter_table("ai_call_records") as batch_op:
        batch_op.add_column(sa.Column("workflow_run_id", sa.String(length=36), nullable=True))
        batch_op.create_foreign_key(
            "fk_ai_call_records_workflow_run_id",
            "diagnosis_workflow_runs",
            ["workflow_run_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch_op.create_unique_constraint(
            "uq_ai_call_records_workflow_run_id",
            ["workflow_run_id"],
        )


def downgrade() -> None:
    with op.batch_alter_table("ai_call_records") as batch_op:
        batch_op.drop_constraint(
            "uq_ai_call_records_workflow_run_id",
            type_="unique",
        )
        batch_op.drop_constraint(
            "fk_ai_call_records_workflow_run_id",
            type_="foreignkey",
        )
        batch_op.drop_column("workflow_run_id")
