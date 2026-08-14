"""add LangGraph diagnosis workflow business records

Revision ID: 20260813_0016
Revises: 20260730_0015
Create Date: 2026-08-13
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260813_0016"
down_revision: str | None = "20260730_0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "diagnosis_workflow_runs",
        sa.Column(
            "device_id",
            sa.String(36),
            sa.ForeignKey("devices.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "diagnosis_result_id",
            sa.String(36),
            sa.ForeignKey("diagnosis_results.id", ondelete="CASCADE"),
            unique=True,
        ),
        sa.Column("graph_thread_id", sa.String(200), nullable=False, unique=True),
        sa.Column("graph_version", sa.String(100), nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("current_node", sa.String(100)),
        sa.Column("question", sa.Text()),
        sa.Column("evidence_score", sa.Float()),
        sa.Column("guidance_level", sa.Integer()),
        sa.Column("needs_rag", sa.Boolean(), nullable=False),
        sa.Column("needs_teacher", sa.Boolean(), nullable=False),
        sa.Column("rule_engine_version", sa.String(100)),
        sa.Column("fault_tree_version", sa.String(100)),
        sa.Column("embedding_version", sa.String(100)),
        sa.Column("model_id", sa.String(200)),
        sa.Column("node_trace", sa.JSON(), nullable=False),
        sa.Column("review_request", sa.JSON()),
        sa.Column("final_result", sa.JSON()),
        sa.Column("error_messages", sa.JSON(), nullable=False),
        sa.Column("is_test_data", sa.Boolean(), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_diagnosis_workflow_device_created",
        "diagnosis_workflow_runs",
        ["device_id", "created_at"],
    )
    op.create_index(
        "ix_diagnosis_workflow_status_updated",
        "diagnosis_workflow_runs",
        ["status", "updated_at"],
    )
    op.create_index(
        "ix_diagnosis_workflow_runs_status",
        "diagnosis_workflow_runs",
        ["status"],
    )
    op.create_table(
        "diagnosis_workflow_reviews",
        sa.Column(
            "workflow_run_id",
            sa.String(36),
            sa.ForeignKey("diagnosis_workflow_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "reviewer_user_id",
            sa.String(36),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("action", sa.String(20), nullable=False),
        sa.Column("comment", sa.Text()),
        sa.Column("edited_result", sa.JSON()),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("id", sa.String(36), primary_key=True),
    )
    op.create_index(
        "ix_diagnosis_workflow_reviews_run_created",
        "diagnosis_workflow_reviews",
        ["workflow_run_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_diagnosis_workflow_reviews_run_created",
        table_name="diagnosis_workflow_reviews",
    )
    op.drop_table("diagnosis_workflow_reviews")
    op.drop_index("ix_diagnosis_workflow_runs_status", table_name="diagnosis_workflow_runs")
    op.drop_index(
        "ix_diagnosis_workflow_status_updated",
        table_name="diagnosis_workflow_runs",
    )
    op.drop_index(
        "ix_diagnosis_workflow_device_created",
        table_name="diagnosis_workflow_runs",
    )
    op.drop_table("diagnosis_workflow_runs")
