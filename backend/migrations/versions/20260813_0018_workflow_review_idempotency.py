"""make workflow review persistence replay-safe

Revision ID: 20260813_0018
Revises: 20260813_0017
Create Date: 2026-08-13
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260813_0018"
down_revision: str | None = "20260813_0017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    duplicate = op.get_bind().execute(
        sa.text(
            """
            SELECT workflow_run_id, COUNT(*) AS review_count
            FROM diagnosis_workflow_reviews
            GROUP BY workflow_run_id
            HAVING COUNT(*) > 1
            LIMIT 1
            """
        )
    ).first()
    if duplicate is not None:
        raise RuntimeError(
            "cannot add one-review-per-workflow constraint: "
            "duplicate diagnosis workflow reviews must be resolved first"
        )
    op.create_unique_constraint(
        "uq_diagnosis_workflow_reviews_workflow_run",
        "diagnosis_workflow_reviews",
        ["workflow_run_id"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_diagnosis_workflow_reviews_workflow_run",
        "diagnosis_workflow_reviews",
        type_="unique",
    )
