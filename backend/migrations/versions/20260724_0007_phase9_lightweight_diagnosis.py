"""phase 9 lightweight deterministic-first diagnosis

Revision ID: 20260724_0007
Revises: 20260723_0006
"""

import sqlalchemy as sa
from alembic import op

revision = "20260724_0007"
down_revision = "20260723_0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("knowledge_chunks", sa.Column("metadata_json", sa.JSON(), nullable=True))
    op.execute("UPDATE knowledge_chunks SET metadata_json = '{}' WHERE metadata_json IS NULL")
    op.alter_column("knowledge_chunks", "metadata_json", nullable=False)

    op.add_column("diagnosis_results", sa.Column("deterministic_core", sa.JSON()))
    op.add_column("diagnosis_results", sa.Column("deterministic_explanation", sa.JSON()))
    op.add_column("diagnosis_results", sa.Column("ai_enhancement", sa.JSON()))

    op.create_table(
        "diagnosis_episodes",
        sa.Column("device_id", sa.String(36), nullable=False),
        sa.Column("experiment_id", sa.String(200)),
        sa.Column("primary_error_code", sa.String(100), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("failure_count", sa.Integer(), nullable=False),
        sa.Column("latest_context_fingerprint", sa.String(64), nullable=False),
        sa.Column("current_hint_level", sa.Integer(), nullable=False),
        sa.Column("last_diagnosis_result_id", sa.String(36), nullable=False),
        sa.Column("ai_call_count", sa.Integer(), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True)),
        sa.Column("resolution_source", sa.String(100)),
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["device_id"], ["devices.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["last_diagnosis_result_id"], ["diagnosis_results.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_diagnosis_episodes_device_status",
        "diagnosis_episodes",
        ["device_id", "status"],
    )
    op.create_index(
        "ix_diagnosis_episodes_device_last_seen",
        "diagnosis_episodes",
        ["device_id", "last_seen_at"],
    )

    op.create_table(
        "ai_explanation_cache",
        sa.Column("fingerprint", sa.String(64), nullable=False),
        sa.Column("explanation_json", sa.JSON(), nullable=False),
        sa.Column("provider", sa.String(100)),
        sa.Column("model_name", sa.String(200)),
        sa.Column("prompt_version", sa.String(100), nullable=False),
        sa.Column("schema_version", sa.String(100), nullable=False),
        sa.Column("ruleset_version", sa.String(100), nullable=False),
        sa.Column("fault_tree_version", sa.String(100)),
        sa.Column("knowledge_version", sa.String(100)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("hit_count", sa.Integer(), nullable=False),
        sa.Column("last_hit_at", sa.DateTime(timezone=True)),
        sa.Column("id", sa.String(36), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("fingerprint"),
    )
    op.create_index("ix_ai_explanation_cache_expires", "ai_explanation_cache", ["expires_at"])

    for name, column in (
        ("episode_id", sa.Column("episode_id", sa.String(36))),
        ("trigger_reason", sa.Column("trigger_reason", sa.String(100))),
        ("cache_status", sa.Column("cache_status", sa.String(30))),
        ("route", sa.Column("route", sa.String(30))),
        ("estimated_cost", sa.Column("estimated_cost", sa.Float())),
        ("latency_ms", sa.Column("latency_ms", sa.Integer())),
        ("validation_status", sa.Column("validation_status", sa.String(30))),
        ("fallback_reason", sa.Column("fallback_reason", sa.String(200))),
    ):
        del name
        op.add_column("ai_call_records", column)
    op.create_foreign_key(
        "fk_ai_call_records_episode",
        "ai_call_records",
        "diagnosis_episodes",
        ["episode_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_ai_call_records_episode_created",
        "ai_call_records",
        ["episode_id", "created_at"],
    )

    if op.get_bind().dialect.name == "postgresql":
        op.execute(
            "CREATE INDEX ix_knowledge_chunks_fts_simple "
            "ON knowledge_chunks USING gin (to_tsvector('simple', content))"
        )


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute("DROP INDEX IF EXISTS ix_knowledge_chunks_fts_simple")
    op.drop_index("ix_ai_call_records_episode_created", table_name="ai_call_records")
    op.drop_constraint("fk_ai_call_records_episode", "ai_call_records", type_="foreignkey")
    for name in (
        "fallback_reason",
        "validation_status",
        "latency_ms",
        "estimated_cost",
        "route",
        "cache_status",
        "trigger_reason",
        "episode_id",
    ):
        op.drop_column("ai_call_records", name)
    op.drop_index("ix_ai_explanation_cache_expires", table_name="ai_explanation_cache")
    op.drop_table("ai_explanation_cache")
    op.drop_index("ix_diagnosis_episodes_device_last_seen", table_name="diagnosis_episodes")
    op.drop_index("ix_diagnosis_episodes_device_status", table_name="diagnosis_episodes")
    op.drop_table("diagnosis_episodes")
    op.drop_column("diagnosis_results", "ai_enhancement")
    op.drop_column("diagnosis_results", "deterministic_explanation")
    op.drop_column("diagnosis_results", "deterministic_core")
    op.drop_column("knowledge_chunks", "metadata_json")
