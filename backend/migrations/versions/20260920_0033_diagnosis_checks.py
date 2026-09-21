"""Persist new check commands without rewriting historical diagnoses."""

import sqlalchemy as sa
from alembic import op

revision = "20260920_0033"
down_revision = "20260920_0032"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "diagnosis_checks",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "session_id", sa.String(36), sa.ForeignKey("experiment_sessions.id"), nullable=False
        ),
        sa.Column("student_user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("device_id", sa.String(36), sa.ForeignKey("devices.id"), nullable=False),
        sa.Column("request_id", sa.String(36), nullable=False),
        sa.Column("request_payload", sa.JSON(), nullable=False),
        sa.Column("payload_hash", sa.String(64), nullable=False),
        sa.Column("baseline_id", sa.String(36), sa.ForeignKey("diagnosis_results.id")),
        sa.Column("workflow_id", sa.String(36), sa.ForeignKey("diagnosis_workflow_runs.id")),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("input_signature", sa.String(64), nullable=False),
        sa.Column("context_snapshot", sa.JSON(), nullable=False),
        sa.Column("result", sa.JSON()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("session_id", "request_id", name="uq_check_session_request"),
    )

    op.create_index(
        "ix_diagnosis_checks_session_created", "diagnosis_checks", ["session_id", "created_at"]
    )


def downgrade():
    if op.get_bind().scalar(sa.text("SELECT count(*) FROM diagnosis_checks")):
        raise RuntimeError("Cannot discard persisted check receipts; archive them explicitly first")
    op.drop_table("diagnosis_checks")
