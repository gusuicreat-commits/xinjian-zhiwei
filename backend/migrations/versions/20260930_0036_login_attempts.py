"""Shared, expiring login admission reservations.

Revision ID: 20260930_0036
Revises: 20260927_0035
"""

import sqlalchemy as sa
from alembic import op

revision = "20260930_0036"
down_revision = "20260927_0035"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "login_attempts",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("key_hash", sa.String(64), nullable=False),
        sa.Column("status", sa.String(10), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status = 'pending' OR status = 'failed'", name="ck_login_attempt_status"
        ),
    )
    op.create_index("ix_login_attempt_key_expiry", "login_attempts", ["key_hash", "expires_at"])
    op.create_index("ix_login_attempt_expiry", "login_attempts", ["expires_at"])


def downgrade():
    # Do not silently reset a live security window when rolling back.
    active = (
        op.get_bind()
        .execute(
            sa.text("SELECT count(*) FROM login_attempts WHERE expires_at > CURRENT_TIMESTAMP")
        )
        .scalar_one()
    )
    if active:
        raise RuntimeError("Wait for active login reservations to expire before downgrade")
    op.drop_table("login_attempts")
