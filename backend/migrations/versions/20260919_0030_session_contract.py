"""Pin new sessions and retain idempotent session command receipts; do not backfill."""

import sqlalchemy as sa
from alembic import op

revision = "20260919_0030"
down_revision = "20260917_0029"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("experiment_sessions", sa.Column("experiment_version_id", sa.String(36)))
    op.create_foreign_key(
        "fk_experiment_sessions_version",
        "experiment_sessions",
        "experiment_versions",
        ["experiment_version_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.add_column(
        "experiment_sessions",
        sa.Column("version_no", sa.Integer(), server_default="1", nullable=False),
    )
    op.create_table(
        "experiment_session_commands",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "actor_user_id",
            sa.String(36),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "session_id",
            sa.String(36),
            sa.ForeignKey("experiment_sessions.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("request_id", sa.String(36), nullable=False),
        sa.Column("payload_hash", sa.String(64), nullable=False),
        sa.Column("result_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("actor_user_id", "request_id", name="uq_session_command_actor_request"),
    )


def downgrade():
    op.drop_table("experiment_session_commands")
    op.drop_column("experiment_sessions", "version_no")
    op.drop_constraint("fk_experiment_sessions_version", "experiment_sessions", type_="foreignkey")
    op.drop_column("experiment_sessions", "experiment_version_id")
