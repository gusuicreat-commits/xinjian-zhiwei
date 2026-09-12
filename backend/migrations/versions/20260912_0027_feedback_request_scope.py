"""Bind new feedback to a session and a retry-stable request identity.

Revision ID: 20260912_0027
Revises: 20260904_0026
Historical feedback stays unscoped; do not invent request IDs or ownership.
"""

import sqlalchemy as sa
from alembic import op

revision = "20260912_0027"
down_revision = "20260904_0026"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("diagnosis_feedback", sa.Column("request_id", sa.String(36), nullable=True))
    op.add_column(
        "diagnosis_feedback", sa.Column("experiment_session_id", sa.String(36), nullable=True)
    )
    op.add_column(
        "diagnosis_feedback", sa.Column("processing_status", sa.String(20), nullable=True)
    )
    op.create_foreign_key(
        "fk_feedback_experiment_session",
        "diagnosis_feedback",
        "experiment_sessions",
        ["experiment_session_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_unique_constraint(
        "uq_feedback_diagnosis_request", "diagnosis_feedback", ["diagnosis_result_id", "request_id"]
    )


def downgrade():
    op.drop_constraint("uq_feedback_diagnosis_request", "diagnosis_feedback", type_="unique")
    op.drop_constraint("fk_feedback_experiment_session", "diagnosis_feedback", type_="foreignkey")
    op.drop_column("diagnosis_feedback", "processing_status")
    op.drop_column("diagnosis_feedback", "experiment_session_id")
    op.drop_column("diagnosis_feedback", "request_id")
