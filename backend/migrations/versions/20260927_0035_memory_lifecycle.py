"""Add memory provenance and governance; leave historical facts untouched."""

import sqlalchemy as sa
from alembic import op

revision = "20260927_0035"
down_revision = "20260927_0034"
branch_labels = None
depends_on = None


def _identity():
    return [
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    ]


def _actor(name="actor_user_id"):
    return sa.Column(
        name, sa.String(36), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )


def _diagnosis():
    return sa.Column(
        "diagnosis_result_id",
        sa.String(36),
        sa.ForeignKey("diagnosis_results.id", ondelete="RESTRICT"),
        nullable=False,
    )


def upgrade():
    op.create_table(
        "memory_uses",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("source_key", sa.String(64), nullable=False),
        sa.Column("source", sa.JSON(), nullable=False),
        _diagnosis(),
        sa.Column("target_type", sa.String(30), nullable=False),
        sa.Column("target_id", sa.String(100), nullable=False),
        sa.Column("use_kind", sa.String(30), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_memory_use_source", "memory_uses", ["source_key", "diagnosis_result_id"])
    op.create_index("ix_memory_use_target", "memory_uses", ["target_type", "target_id"])
    op.create_index("ix_memory_use_diagnosis", "memory_uses", ["diagnosis_result_id", "id"])
    op.create_table(
        "memory_events",
        *_identity(),
        _actor(),
        sa.Column("source_key", sa.String(64), nullable=False),
        sa.Column("source", sa.JSON(), nullable=False),
        sa.Column("reason", sa.String(2000), nullable=False),
        sa.Column("cache_cleanup_status", sa.String(30), nullable=False),
        sa.UniqueConstraint("source_key", name="uq_memory_event_source"),
    )
    op.create_index("ix_memory_event_pending", "memory_events", ["cache_cleanup_status", "id"])
    op.create_table(
        "memory_impact_reviews",
        *_identity(),
        _actor("reviewer_user_id"),
        _diagnosis(),
        sa.Column(
            "event_id",
            sa.String(36),
            sa.ForeignKey("memory_events.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("decision", sa.String(30), nullable=False),
        sa.Column("note", sa.String(2000), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.UniqueConstraint("event_id", "diagnosis_result_id", name="uq_memory_impact_review"),
    )
    op.create_table(
        "memory_cleanup_plans",
        *_identity(),
        _actor(),
        sa.Column("cutoff", sa.DateTime(timezone=True), nullable=False),
        sa.Column("targets", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("result", sa.JSON(), nullable=False),
    )


def downgrade():
    bind = op.get_bind()
    tables = ["memory_impact_reviews", "memory_uses", "memory_events", "memory_cleanup_plans"]
    if any(bind.execute(sa.text(f"SELECT 1 FROM {name} LIMIT 1")).first() for name in tables):
        raise RuntimeError("memory governance history must not be destroyed by downgrade")
    for name in tables:
        op.drop_table(name)
