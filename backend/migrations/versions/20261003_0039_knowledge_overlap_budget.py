"""Account only server-created overlap when bounding knowledge workspace edits."""

import sqlalchemy as sa
from alembic import op

revision = "20261003_0039"
down_revision = "20261002_0038"
branch_labels = None
depends_on = None


def upgrade():
    # Historical locators may describe text already edited: never guess credit.
    op.add_column(
        "knowledge_chunks",
        sa.Column("overlap_credit_chars", sa.Integer(), nullable=False, server_default="0"),
    )
    op.create_check_constraint(
        "ck_knowledge_chunk_overlap_credit",
        "knowledge_chunks",
        "overlap_credit_chars >= 0 AND overlap_credit_chars <= length(content)",
    )


def downgrade():
    if op.get_bind().scalar(
        sa.text("SELECT count(*) FROM knowledge_chunks WHERE overlap_credit_chars <> 0")
    ):
        raise RuntimeError("Recorded overlap accounting cannot be discarded; retain the column")
    op.drop_constraint("ck_knowledge_chunk_overlap_credit", "knowledge_chunks", type_="check")
    op.drop_column("knowledge_chunks", "overlap_credit_chars")
