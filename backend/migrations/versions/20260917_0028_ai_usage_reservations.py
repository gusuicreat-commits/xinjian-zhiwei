"""Reserve AI quota before each outbound attempt; preserve historical audit rows."""

import sqlalchemy as sa
from alembic import op

revision = "20260917_0028"
down_revision = "20260912_0027"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("diagnosis_results", sa.Column("episode_id", sa.String(36), nullable=True))
    op.create_foreign_key(
        "fk_diagnosis_results_episode", "diagnosis_results", "diagnosis_episodes",
        ["episode_id"], ["id"], ondelete="SET NULL",
    )
    op.add_column(
        "ai_call_records",
        sa.Column("quota_managed", sa.Boolean(), server_default=sa.false(), nullable=False),
    )
    op.create_table(
        "ai_usage_reservations",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("diagnosis_result_id", sa.String(36),
                  sa.ForeignKey("diagnosis_results.id", ondelete="CASCADE"), nullable=False),
        sa.Column("device_id", sa.String(36),
                  sa.ForeignKey("devices.id", ondelete="CASCADE"), nullable=False),
        sa.Column("episode_id", sa.String(36),
                  sa.ForeignKey("diagnosis_episodes.id", ondelete="SET NULL")),
        sa.Column("call_stage", sa.String(100), nullable=False),
        sa.Column("provider", sa.String(100), nullable=False),
        sa.Column("model", sa.String(200), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("reserved_cost", sa.Float()),
        sa.Column("accounted_cost", sa.Float()),
        sa.Column("input_tokens", sa.Integer()),
        sa.Column("output_tokens", sa.Integer()),
        sa.Column("error_code", sa.String(100)),
        sa.Column("is_test_data", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_ai_usage_device_created", "ai_usage_reservations",
                    ["device_id", "created_at"])
    op.create_index("ix_ai_usage_created", "ai_usage_reservations", ["created_at"])


def downgrade():
    op.drop_table("ai_usage_reservations")
    op.drop_column("ai_call_records", "quota_managed")
    op.drop_constraint("fk_diagnosis_results_episode", "diagnosis_results", type_="foreignkey")
    op.drop_column("diagnosis_results", "episode_id")
