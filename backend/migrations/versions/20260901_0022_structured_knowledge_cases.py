"""Add structured knowledge cases for the no-RAG MVP.

Revision ID: 20260901_0022
Revises: 20260818_0021
Create Date: 2026-09-01
"""

from collections.abc import Sequence
from typing import Optional, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20260901_0022"
down_revision: Optional[str] = "20260818_0021"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "knowledge_cases",
        sa.Column("id", sa.String(length=100), nullable=False),
        sa.Column("experiment_type", sa.String(length=100), nullable=False),
        sa.Column("error_type", sa.String(length=100), nullable=False),
        sa.Column("symptom", sa.Text(), nullable=False),
        sa.Column("normal_state", sa.JSON(), nullable=False),
        sa.Column("evidence", sa.JSON(), nullable=False),
        sa.Column("possible_causes", sa.JSON(), nullable=False),
        sa.Column("solution_steps", sa.JSON(), nullable=False),
        sa.Column("teacher_notes", sa.Text(), nullable=True),
        sa.Column("review_status", sa.String(length=20), nullable=False),
        sa.Column("source_ref", sa.String(length=500), nullable=False),
        sa.Column("version", sa.String(length=50), nullable=False),
        sa.Column("is_test_data", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_knowledge_cases_review_status", "knowledge_cases", ["review_status"])
    op.create_index(
        "ix_knowledge_cases_match",
        "knowledge_cases",
        ["experiment_type", "error_type", "review_status"],
    )


def downgrade() -> None:
    op.drop_index("ix_knowledge_cases_match", table_name="knowledge_cases")
    op.drop_index("ix_knowledge_cases_review_status", table_name="knowledge_cases")
    op.drop_table("knowledge_cases")

