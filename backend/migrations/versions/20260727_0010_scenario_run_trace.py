"""trace synthetic scenario runs for targeted cleanup

Revision ID: 20260727_0010
Revises: 20260727_0009
"""

import sqlalchemy as sa
from alembic import op

revision = "20260727_0010"
down_revision = "20260727_0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "ingestion_requests",
        sa.Column("test_run_id", sa.String(length=36), nullable=True),
    )
    op.create_index(
        "ix_ingestion_requests_test_run",
        "ingestion_requests",
        ["test_run_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_ingestion_requests_test_run",
        table_name="ingestion_requests",
    )
    op.drop_column("ingestion_requests", "test_run_id")
