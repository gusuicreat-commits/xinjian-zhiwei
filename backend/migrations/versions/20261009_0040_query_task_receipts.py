"""Persist deterministic query tasks, questions and answer receipts in business DB."""

import sqlalchemy as sa
from alembic import op

revision = "20261009_0040"
down_revision = "20261003_0039"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "query_tasks",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "session_id", sa.String(36), sa.ForeignKey("experiment_sessions.id"), nullable=False
        ),
        sa.Column(
            "diagnosis_id", sa.String(36), sa.ForeignKey("diagnosis_results.id"), nullable=False
        ),
        sa.Column("experiment_version_id", sa.String(36), sa.ForeignKey("experiment_versions.id")),
        sa.Column("contract_version", sa.String(40), nullable=False),
        sa.Column("scope_snapshot", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("terminal_reason", sa.String(40)),
        sa.Column("requirements", sa.JSON(), nullable=False),
        sa.Column("source_manifest", sa.JSON(), nullable=False),
        sa.Column("query_count", sa.Integer(), nullable=False),
        sa.Column("question_count", sa.Integer(), nullable=False),
        sa.Column("elapsed_ms", sa.Integer(), nullable=False),
        sa.Column("is_test_data", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("session_id", "diagnosis_id", name="uq_query_session_diagnosis"),
        sa.CheckConstraint("query_count >= 0 AND query_count <= 4", name="ck_query_count"),
        sa.CheckConstraint(
            "question_count >= 0 AND question_count <= 1", name="ck_query_question_count"
        ),
    )
    op.create_table(
        "query_questions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("task_id", sa.String(36), sa.ForeignKey("query_tasks.id"), nullable=False),
        sa.Column("requirement", sa.String(50), nullable=False),
        sa.Column("question_id", sa.String(100), nullable=False),
        sa.Column("version", sa.String(40), nullable=False),
        sa.Column("experiment_version_id", sa.String(36), sa.ForeignKey("experiment_versions.id")),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("closed_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint(
            "task_id", "requirement", "question_id", "version", name="uq_query_question_version"
        ),
        sa.UniqueConstraint("task_id", "requirement", name="uq_query_question_requirement"),
        sa.UniqueConstraint("task_id", "id", name="uq_query_question_owner"),
    )
    op.create_table(
        "query_answer_receipts",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("task_id", sa.String(36), sa.ForeignKey("query_tasks.id"), nullable=False),
        sa.Column("question_record_id", sa.String(36), nullable=False),
        sa.Column("request_id", sa.String(36), nullable=False),
        sa.Column("payload_hash", sa.String(64), nullable=False),
        sa.Column("value", sa.String(20), nullable=False),
        sa.Column("submitted_by_user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("is_test_data", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["task_id", "question_record_id"], ["query_questions.task_id", "query_questions.id"]
        ),
        sa.UniqueConstraint("task_id", "request_id", name="uq_query_answer_request"),
        sa.UniqueConstraint("question_record_id", name="uq_query_answer_question"),
        sa.CheckConstraint(
            "CAST(value AS TEXT) IN ('matches_table', 'differs', 'unclear')",
            name="ck_query_answer_value",
        ),
    )


def downgrade():
    # Explicit rollback discards this feature's receipts only, child before parent.
    op.drop_table("query_answer_receipts")
    op.drop_table("query_questions")
    op.drop_table("query_tasks")
