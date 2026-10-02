"""Explicit workspace source grants, with no guessed historical ownership."""

import sqlalchemy as sa
from alembic import op

revision = "20261002_0037"
down_revision = "20260930_0036"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "knowledge_documents", sa.Column("submitted_by_user_id", sa.String(36), nullable=True)
    )
    op.create_foreign_key(
        "fk_knowledge_documents_submitter",
        "knowledge_documents",
        "users",
        ["submitted_by_user_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_table(
        "knowledge_source_grants",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "source_id",
            sa.String(36),
            sa.ForeignKey("knowledge_sources.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("capability", sa.String(20), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("source_id", "user_id", "capability", name="uq_knowledge_source_grant"),
        sa.CheckConstraint(
            "CAST(capability AS TEXT) IN ('organize', 'review')", name="ck_source_grant_capability"
        ),
    )
    op.create_index(
        "ix_source_grants_user_source", "knowledge_source_grants", ["user_id", "source_id"]
    )


def downgrade():
    raise RuntimeError(
        "Workspace grants cannot be losslessly downgraded; disable workspace writes instead"
    )
