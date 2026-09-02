"""Add teacher-reviewed AI-assisted knowledge case drafts.

Revision ID: 20260901_0024
Revises: 20260901_0023
Create Date: 2026-09-01
"""

from collections.abc import Sequence
from typing import Optional, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20260901_0024"
down_revision: Optional[str] = "20260901_0023"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "knowledge_case_drafts",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("diagnosis_result_id", sa.String(length=36), nullable=False),
        sa.Column("feedback_id", sa.String(length=36), nullable=False),
        sa.Column("experiment_type", sa.String(length=100), nullable=False),
        sa.Column("error_type", sa.String(length=100), nullable=False),
        sa.Column("fact_snapshot", sa.JSON(), nullable=False),
        sa.Column("template_payload", sa.JSON(), nullable=False),
        sa.Column("polished_payload", sa.JSON(), nullable=True),
        sa.Column("quality_checks", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("reviewer_ref", sa.String(length=200), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("is_test_data", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["diagnosis_result_id"], ["diagnosis_results.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["feedback_id"], ["diagnosis_feedback.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "diagnosis_result_id",
            "feedback_id",
            name="uq_knowledge_case_drafts_diagnosis_feedback",
        ),
    )
    op.create_index(
        "ix_knowledge_case_drafts_status_created",
        "knowledge_case_drafts",
        ["status", "created_at"],
    )
    op.create_index(
        "ix_knowledge_case_drafts_status",
        "knowledge_case_drafts",
        ["status"],
    )


def downgrade() -> None:
    op.drop_index("ix_knowledge_case_drafts_status", table_name="knowledge_case_drafts")
    op.drop_index(
        "ix_knowledge_case_drafts_status_created",
        table_name="knowledge_case_drafts",
    )
    op.drop_table("knowledge_case_drafts")
