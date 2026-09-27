"""Account for legacy telemetry in the shared device admission quota."""

import sqlalchemy as sa
from alembic import op

revision = "20260927_0034"
down_revision = "20260920_0033"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "legacy_ingestion_admissions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "device_id",
            sa.String(36),
            sa.ForeignKey("devices.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_legacy_admission_device_received",
        "legacy_ingestion_admissions",
        ["device_id", "received_at"],
    )


def downgrade():
    op.drop_table("legacy_ingestion_admissions")
