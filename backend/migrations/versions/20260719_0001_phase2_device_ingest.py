"""Create Phase 2 device ingestion tables.

Revision ID: 20260719_0001
Revises:
Create Date: 2026-07-19
"""

from collections.abc import Sequence
from typing import Optional, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20260719_0001"
down_revision: Optional[str] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table(
        "devices",
        sa.Column("device_key", sa.String(length=128), nullable=False),
        sa.Column("display_name", sa.String(length=200), nullable=True),
        sa.Column("device_type", sa.String(length=100), nullable=True),
        sa.Column("hardware_model", sa.String(length=200), nullable=True),
        sa.Column("token_hash", sa.String(length=512), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("firmware_version", sa.String(length=100), nullable=True),
        sa.Column("metadata", sa.JSON(), nullable=False),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_devices_device_key", "devices", ["device_key"], unique=True)
    op.create_index("ix_devices_last_seen_at", "devices", ["last_seen_at"], unique=False)

    op.create_table(
        "device_logs",
        sa.Column("device_id", sa.String(length=36), nullable=False),
        sa.Column("level", sa.String(length=20), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("event_code", sa.String(length=100), nullable=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("sensor_snapshot", sa.JSON(), nullable=False),
        sa.Column("raw_payload", sa.JSON(), nullable=False),
        sa.Column("is_test_data", sa.Boolean(), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.ForeignKeyConstraint(["device_id"], ["devices.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_device_logs_event_code", "device_logs", ["event_code"], unique=False)
    op.create_index(
        "ix_device_logs_device_occurred",
        "device_logs",
        ["device_id", "occurred_at"],
        unique=False,
    )

    op.create_table(
        "sensor_readings",
        sa.Column("device_id", sa.String(length=36), nullable=False),
        sa.Column("sensor_type", sa.String(length=100), nullable=False),
        sa.Column("metric_key", sa.String(length=100), nullable=False),
        sa.Column("value", sa.Float(), nullable=False),
        sa.Column("unit", sa.String(length=50), nullable=True),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("metadata", sa.JSON(), nullable=False),
        sa.Column("raw_payload", sa.JSON(), nullable=False),
        sa.Column("is_test_data", sa.Boolean(), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.ForeignKeyConstraint(["device_id"], ["devices.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_sensor_readings_device_observed",
        "sensor_readings",
        ["device_id", "observed_at"],
        unique=False,
    )
    op.create_index(
        "ix_sensor_readings_metric_observed",
        "sensor_readings",
        ["metric_key", "observed_at"],
        unique=False,
    )

    op.create_table(
        "device_heartbeats",
        sa.Column("device_id", sa.String(length=36), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("firmware_version", sa.String(length=100), nullable=True),
        sa.Column("metadata", sa.JSON(), nullable=False),
        sa.Column("raw_payload", sa.JSON(), nullable=False),
        sa.Column("is_test_data", sa.Boolean(), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.ForeignKeyConstraint(["device_id"], ["devices.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_device_heartbeats_device_observed",
        "device_heartbeats",
        ["device_id", "observed_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_device_heartbeats_device_observed", table_name="device_heartbeats")
    op.drop_table("device_heartbeats")
    op.drop_index("ix_sensor_readings_metric_observed", table_name="sensor_readings")
    op.drop_index("ix_sensor_readings_device_observed", table_name="sensor_readings")
    op.drop_table("sensor_readings")
    op.drop_index("ix_device_logs_device_occurred", table_name="device_logs")
    op.drop_index("ix_device_logs_event_code", table_name="device_logs")
    op.drop_table("device_logs")
    op.drop_index("ix_devices_last_seen_at", table_name="devices")
    op.drop_index("ix_devices_device_key", table_name="devices")
    op.drop_table("devices")
