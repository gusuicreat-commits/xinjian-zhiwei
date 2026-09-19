"""Durable event ownership, optimistic draft publication, episode evidence revisions.

Historical associations remain NULL. This migration never guesses historical ownership.
"""

import sqlalchemy as sa
from alembic import op

revision = "20260917_0029"
down_revision = "20260917_0028"
branch_labels = None
depends_on = None


def upgrade():
    for table in ("device_logs", "sensor_readings", "device_heartbeats"):
        op.add_column(table, sa.Column("experiment_session_id", sa.String(36), nullable=True))
        op.create_foreign_key(
            f"fk_{table}_experiment_session",
            table,
            "experiment_sessions",
            ["experiment_session_id"],
            ["id"],
            ondelete="SET NULL",
        )
        op.create_index(f"ix_{table}_experiment_session_id", table, ["experiment_session_id"])
    op.add_column(
        "knowledge_case_drafts",
        sa.Column("version_no", sa.Integer(), nullable=False, server_default="1"),
    )
    op.add_column("knowledge_cases", sa.Column("source_draft_id", sa.String(36), nullable=True))
    op.create_foreign_key(
        "fk_knowledge_cases_source_draft",
        "knowledge_cases",
        "knowledge_case_drafts",
        ["source_draft_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_unique_constraint(
        "uq_knowledge_cases_source_draft_id", "knowledge_cases", ["source_draft_id"]
    )
    op.add_column(
        "diagnosis_episodes",
        sa.Column("evidence_revision", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "diagnosis_results", sa.Column("episode_evidence_revision", sa.Integer(), nullable=True)
    )


def downgrade():
    op.drop_column("diagnosis_results", "episode_evidence_revision")
    op.drop_column("diagnosis_episodes", "evidence_revision")
    op.drop_constraint("uq_knowledge_cases_source_draft_id", "knowledge_cases", type_="unique")
    op.drop_constraint("fk_knowledge_cases_source_draft", "knowledge_cases", type_="foreignkey")
    op.drop_column("knowledge_cases", "source_draft_id")
    op.drop_column("knowledge_case_drafts", "version_no")
    for table in ("device_heartbeats", "sensor_readings", "device_logs"):
        op.drop_index(f"ix_{table}_experiment_session_id", table_name=table)
        op.drop_constraint(f"fk_{table}_experiment_session", table, type_="foreignkey")
        op.drop_column(table, "experiment_session_id")
