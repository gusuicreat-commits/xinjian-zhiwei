"""device protocol v1 idempotent batch ingestion

Revision ID: 20260727_0009
Revises: 20260725_0008
"""

import sqlalchemy as sa
from alembic import op

revision = "20260727_0009"
down_revision = "20260725_0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ingestion_requests",
        sa.Column("device_id", sa.String(length=36), nullable=False),
        sa.Column("request_id", sa.String(length=36), nullable=False),
        sa.Column("protocol_version", sa.String(length=20), nullable=False),
        sa.Column("schema_version", sa.String(length=20), nullable=False),
        sa.Column("boot_id", sa.String(length=100), nullable=False),
        sa.Column("sequence_no", sa.Integer(), nullable=False),
        sa.Column("firmware_version", sa.String(length=100), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("uptime_ms", sa.Integer(), nullable=True),
        sa.Column("payload_hash", sa.String(length=64), nullable=False),
        sa.Column("record_count", sa.Integer(), nullable=False),
        sa.Column("response_json", sa.JSON(), nullable=False),
        sa.Column("is_test_data", sa.Boolean(), nullable=False),
        sa.Column(
            "server_received_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["device_id"], ["devices.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "device_id",
            "boot_id",
            "sequence_no",
            name="uq_ingestion_requests_device_boot_sequence",
        ),
        sa.UniqueConstraint(
            "device_id",
            "request_id",
            name="uq_ingestion_requests_device_request",
        ),
    )
    op.create_index(
        "ix_ingestion_requests_device_received",
        "ingestion_requests",
        ["device_id", "server_received_at"],
        unique=False,
    )

    for table_name in ("device_logs", "sensor_readings", "device_heartbeats"):
        op.add_column(
            table_name,
            sa.Column("ingestion_request_id", sa.String(length=36), nullable=True),
        )
        op.add_column(
            table_name,
            sa.Column("protocol_version", sa.String(length=20), nullable=True),
        )
        op.add_column(
            table_name,
            sa.Column("schema_version", sa.String(length=20), nullable=True),
        )
        op.add_column(
            table_name,
            sa.Column("boot_id", sa.String(length=100), nullable=True),
        )
        op.add_column(
            table_name,
            sa.Column("sequence_no", sa.Integer(), nullable=True),
        )
        op.add_column(
            table_name,
            sa.Column("uptime_ms", sa.Integer(), nullable=True),
        )
        op.add_column(
            table_name,
            sa.Column("time_quality", sa.String(length=30), nullable=True),
        )
        op.create_index(
            f"ix_{table_name}_ingestion_request_id",
            table_name,
            ["ingestion_request_id"],
            unique=False,
        )
        op.create_foreign_key(
            f"fk_{table_name}_ingestion_request_id",
            table_name,
            "ingestion_requests",
            ["ingestion_request_id"],
            ["id"],
            ondelete="SET NULL",
        )


def downgrade() -> None:
    for table_name in ("device_heartbeats", "sensor_readings", "device_logs"):
        op.drop_constraint(
            f"fk_{table_name}_ingestion_request_id",
            table_name,
            type_="foreignkey",
        )
        op.drop_index(
            f"ix_{table_name}_ingestion_request_id",
            table_name=table_name,
        )
        for column_name in (
            "time_quality",
            "uptime_ms",
            "sequence_no",
            "boot_id",
            "schema_version",
            "protocol_version",
            "ingestion_request_id",
        ):
            op.drop_column(table_name, column_name)

    op.drop_index(
        "ix_ingestion_requests_device_received",
        table_name="ingestion_requests",
    )
    op.drop_table("ingestion_requests")
