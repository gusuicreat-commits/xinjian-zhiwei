"""Add PDF V2 evidence and knowledge lifecycle governance fields.

Revision ID: 20260902_0025
Revises: 20260901_0024
Create Date: 2026-09-02
"""

from collections.abc import Sequence
from typing import Optional, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20260902_0025"
down_revision: Optional[str] = "20260901_0024"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("ai_call_records") as batch_op:
        batch_op.alter_column(
            "call_stage",
            existing_type=sa.String(length=30),
            type_=sa.String(length=100),
            existing_nullable=False,
        )

    with op.batch_alter_table("knowledge_cases") as batch_op:
        batch_op.add_column(
            sa.Column("facts", sa.JSON(), nullable=False, server_default="{}")
        )
        batch_op.add_column(sa.Column("root_cause_value", sa.String(length=200)))
        batch_op.add_column(
            sa.Column(
                "root_cause_status",
                sa.String(length=20),
                nullable=False,
                server_default="unknown",
            )
        )
        batch_op.add_column(sa.Column("confirmed_by", sa.String(length=200)))
        batch_op.add_column(sa.Column("confirmed_at", sa.DateTime(timezone=True)))
        batch_op.add_column(
            sa.Column("solution_record", sa.JSON(), nullable=False, server_default="{}")
        )
        batch_op.add_column(
            sa.Column(
                "ai_generated_fields", sa.JSON(), nullable=False, server_default="{}"
            )
        )
        batch_op.add_column(
            sa.Column(
                "source_type",
                sa.String(length=30),
                nullable=False,
                server_default="curated_template",
            )
        )
        batch_op.add_column(
            sa.Column(
                "facts_locked", sa.Boolean(), nullable=False, server_default=sa.false()
            )
        )
        batch_op.add_column(
            sa.Column(
                "quality_check_passed",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            )
        )

    with op.batch_alter_table("knowledge_case_drafts") as batch_op:
        batch_op.add_column(
            sa.Column("root_cause", sa.JSON(), nullable=False, server_default="{}")
        )
        batch_op.add_column(
            sa.Column("solution_record", sa.JSON(), nullable=False, server_default="{}")
        )
        batch_op.add_column(
            sa.Column("source_ids", sa.JSON(), nullable=False, server_default="[]")
        )
        batch_op.add_column(
            sa.Column("allowed_ai_fields", sa.JSON(), nullable=False, server_default="[]")
        )
        batch_op.add_column(
            sa.Column(
                "facts_locked", sa.Boolean(), nullable=False, server_default=sa.true()
            )
        )
        batch_op.add_column(
            sa.Column("ai_audit", sa.JSON(), nullable=False, server_default="{}")
        )

    for table, columns in (
        (
            "knowledge_cases",
            (
                "facts",
                "root_cause_status",
                "solution_record",
                "ai_generated_fields",
                "source_type",
                "facts_locked",
                "quality_check_passed",
            ),
        ),
        (
            "knowledge_case_drafts",
            (
                "root_cause",
                "solution_record",
                "source_ids",
                "allowed_ai_fields",
                "facts_locked",
                "ai_audit",
            ),
        ),
    ):
        for column in columns:
            op.alter_column(table, column, server_default=None)


def downgrade() -> None:
    with op.batch_alter_table("knowledge_case_drafts") as batch_op:
        batch_op.drop_column("ai_audit")
        batch_op.drop_column("facts_locked")
        batch_op.drop_column("allowed_ai_fields")
        batch_op.drop_column("source_ids")
        batch_op.drop_column("solution_record")
        batch_op.drop_column("root_cause")

    with op.batch_alter_table("knowledge_cases") as batch_op:
        batch_op.drop_column("quality_check_passed")
        batch_op.drop_column("facts_locked")
        batch_op.drop_column("source_type")
        batch_op.drop_column("ai_generated_fields")
        batch_op.drop_column("solution_record")
        batch_op.drop_column("confirmed_at")
        batch_op.drop_column("confirmed_by")
        batch_op.drop_column("root_cause_status")
        batch_op.drop_column("root_cause_value")
        batch_op.drop_column("facts")

    with op.batch_alter_table("ai_call_records") as batch_op:
        batch_op.alter_column(
            "call_stage",
            existing_type=sa.String(length=100),
            type_=sa.String(length=30),
            existing_nullable=False,
        )
