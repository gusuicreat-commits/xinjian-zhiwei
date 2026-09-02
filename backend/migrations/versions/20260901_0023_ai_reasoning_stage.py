"""Allow separately audited reasoning and explanation AI calls.

Revision ID: 20260901_0023
Revises: 20260901_0022
Create Date: 2026-09-01
"""

from collections.abc import Sequence
from typing import Optional, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20260901_0023"
down_revision: Optional[str] = "20260901_0022"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("ai_call_records") as batch_op:
        batch_op.add_column(
            sa.Column(
                "call_stage",
                sa.String(length=30),
                nullable=False,
                server_default="explanation",
            )
        )
        batch_op.drop_constraint("uq_ai_call_records_workflow_run_id", type_="unique")
        batch_op.create_unique_constraint(
            "uq_ai_call_records_workflow_stage",
            ["workflow_run_id", "call_stage"],
        )
    op.alter_column("ai_call_records", "call_stage", server_default=None)


def downgrade() -> None:
    op.execute("DELETE FROM ai_call_records WHERE call_stage != 'explanation'")
    with op.batch_alter_table("ai_call_records") as batch_op:
        batch_op.drop_constraint("uq_ai_call_records_workflow_stage", type_="unique")
        batch_op.create_unique_constraint(
            "uq_ai_call_records_workflow_run_id",
            ["workflow_run_id"],
        )
        batch_op.drop_column("call_stage")
