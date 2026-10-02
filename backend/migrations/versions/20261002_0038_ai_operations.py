"""Durable logical AI operations and per-attempt reservation association."""

import sqlalchemy as sa
from alembic import op

revision = "20261002_0038"
down_revision = "20261002_0037"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "ai_operations",
        sa.CheckConstraint(
            "CAST(status AS TEXT) IN ('prepared','dispatching','succeeded',"
            "'failed_known','outcome_unknown')",
            name="ck_ai_operation_status",
        ),
        sa.CheckConstraint("attempt_no >= 0", name="ck_ai_operation_attempt"),
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("operation_key", sa.String(240), nullable=False, unique=True),
        sa.Column(
            "diagnosis_result_id",
            sa.String(36),
            sa.ForeignKey("diagnosis_results.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("call_stage", sa.String(100), nullable=False),
        sa.Column("input_hash", sa.String(64), nullable=False),
        sa.Column("execution_versions", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("attempt_no", sa.Integer(), nullable=False),
        sa.Column("deadline_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("retry_at", sa.DateTime(timezone=True)),
        sa.Column("retry_allowed", sa.Boolean(), nullable=False),
        sa.Column("error_code", sa.String(100)),
        sa.Column("completion", sa.JSON()),
    )
    op.create_index(
        "ix_ai_operations_diagnosis_result_id", "ai_operations", ["diagnosis_result_id"]
    )
    op.create_index("ix_ai_operations_status", "ai_operations", ["status"])
    with op.batch_alter_table("ai_usage_reservations") as batch:
        batch.add_column(sa.Column("operation_id", sa.String(36)))
        batch.add_column(sa.Column("attempt_no", sa.Integer()))
        batch.create_foreign_key(
            "fk_ai_usage_operation", "ai_operations", ["operation_id"], ["id"], ondelete="RESTRICT"
        )
        batch.create_index("ix_ai_usage_reservations_operation_id", ["operation_id"])
        batch.create_unique_constraint(
            "uq_ai_usage_operation_attempt", ["operation_id", "attempt_no"]
        )


def downgrade():
    raise RuntimeError(
        "AI operation state and uncertain costs cannot be discarded; "
        "disable AI before code rollback"
    )
