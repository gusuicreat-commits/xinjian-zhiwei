"""phase 9.5 runtime route and knowledge governance audit

Revision ID: 20260725_0008
Revises: 20260724_0007
"""

import sqlalchemy as sa
from alembic import op

revision = "20260725_0008"
down_revision = "20260724_0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "ai_call_records",
        sa.Column("route_path", sa.String(length=200), nullable=True),
    )
    op.execute(
        """
        UPDATE ai_call_records
        SET route_path = CASE
            WHEN cache_status = 'hit' THEN 'cache_hit'
            WHEN status = 'succeeded' THEN
                'cache_miss → ' || COALESCE(route, 'provider') || '_success'
            WHEN status = 'failed' THEN
                'cache_miss → ' || COALESCE(route, 'provider')
                || '_failed → deterministic_fallback'
            WHEN error_code = 'AI_NOT_CONFIGURED'
                THEN 'ai_disabled → deterministic_only'
            ELSE 'policy_or_gate_skip → deterministic_only'
        END
        """
    )

    op.add_column(
        "knowledge_reviews",
        sa.Column("reviewer_role", sa.String(length=30), nullable=True),
    )
    op.execute(
        "UPDATE knowledge_reviews SET reviewer_role = 'legacy_unspecified' "
        "WHERE reviewer_role IS NULL"
    )
    op.alter_column("knowledge_reviews", "reviewer_role", nullable=False)


def downgrade() -> None:
    op.drop_column("knowledge_reviews", "reviewer_role")
    op.drop_column("ai_call_records", "route_path")
