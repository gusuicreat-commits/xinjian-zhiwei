"""align database constraints with the SQLAlchemy metadata

Revision ID: 20260727_0014
Revises: 20260727_0013
Create Date: 2026-07-27
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260727_0014"
down_revision: str | None = "20260727_0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # The corresponding unique indexes remain in place. These constraints were
    # duplicate declarations created by the first P4/P5 migration drafts.
    op.execute("ALTER TABLE users DROP CONSTRAINT IF EXISTS users_username_key")
    op.execute(
        "ALTER TABLE experiment_templates "
        "DROP CONSTRAINT IF EXISTS experiment_templates_code_key"
    )


def downgrade() -> None:
    op.create_unique_constraint("users_username_key", "users", ["username"])
    op.create_unique_constraint(
        "experiment_templates_code_key",
        "experiment_templates",
        ["code"],
    )
