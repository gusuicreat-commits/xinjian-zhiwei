"""phase 9 provider-independent AI diagnosis framework

Revision ID: 20260723_0006
Revises: 20260721_0005
"""

import sqlalchemy as sa
from alembic import op

revision = "20260723_0006"
down_revision = "20260721_0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ai_call_records",
        sa.Column("diagnosis_result_id", sa.String(length=36), nullable=False),
        sa.Column("provider", sa.String(length=100), nullable=True),
        sa.Column("model", sa.String(length=200), nullable=True),
        sa.Column("transport", sa.String(length=50), nullable=False),
        sa.Column("prompt_version", sa.String(length=100), nullable=False),
        sa.Column("prompt_hash", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("duration_ms", sa.Integer(), nullable=False),
        sa.Column("input_snapshot", sa.JSON(), nullable=False),
        sa.Column("output_json", sa.JSON(), nullable=True),
        sa.Column("knowledge_references", sa.JSON(), nullable=False),
        sa.Column("input_tokens", sa.Integer(), nullable=True),
        sa.Column("output_tokens", sa.Integer(), nullable=True),
        sa.Column("error_code", sa.String(length=100), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("is_test_data", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.ForeignKeyConstraint(
            ["diagnosis_result_id"], ["diagnosis_results.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_ai_calls_diagnosis_created",
        "ai_call_records",
        ["diagnosis_result_id", "created_at"],
    )
    op.create_index(
        "ix_ai_calls_status_created",
        "ai_call_records",
        ["status", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_ai_calls_status_created", table_name="ai_call_records")
    op.drop_index("ix_ai_calls_diagnosis_created", table_name="ai_call_records")
    op.drop_table("ai_call_records")
