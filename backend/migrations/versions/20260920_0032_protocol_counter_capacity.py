"""Widen all ingestion counters without changing historical values."""

import sqlalchemy as sa
from alembic import op

revision = "20260920_0032"
down_revision = "20260919_0031"
branch_labels = None
depends_on = None
TABLES = ("ingestion_requests", "device_heartbeats", "device_logs", "sensor_readings")


def upgrade():
    for table in TABLES:
        for field in ("sequence_no", "uptime_ms"):
            op.alter_column(table, field, existing_type=sa.Integer(), type_=sa.BigInteger())


def downgrade():
    # Refuse before any narrowing; never truncate accepted values on rollback.
    connection = op.get_bind()
    for table in TABLES:
        if connection.scalar(
            sa.text(
                f"SELECT count(*) FROM {table} WHERE sequence_no > 2147483647 "
                "OR sequence_no < -2147483648 OR uptime_ms > 2147483647 "
                "OR uptime_ms < -2147483648"
            )
        ):
            raise RuntimeError("Cannot narrow protocol counters: values exceed 32-bit capacity")
    for table in TABLES:
        for field in ("sequence_no", "uptime_ms"):
            op.alter_column(table, field, existing_type=sa.BigInteger(), type_=sa.Integer())
