"""Independent problem ownership for new diagnoses; historical rows stay unchanged."""

import sqlalchemy as sa
from alembic import op

revision = "20260919_0031"
down_revision = "20260919_0030"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("diagnosis_results", sa.Column("issue_model_version", sa.Integer()))
    op.add_column("ai_usage_reservations", sa.Column("attribution", sa.JSON()))
    op.add_column("guidance_history", sa.Column("help_wait_seconds", sa.Integer()))
    op.add_column("diagnosis_episodes", sa.Column("scope_key", sa.String(64)))
    op.create_index("ix_diagnosis_episodes_scope_key", "diagnosis_episodes", ["scope_key"])
    op.create_index(
        "uq_active_problem_scope",
        "diagnosis_episodes",
        ["scope_key"],
        unique=True,
        postgresql_where=sa.text("scope_key IS NOT NULL AND status IN ('open','escalated')"),
    )
    op.create_table(
        "diagnosis_issues",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "diagnosis_result_id",
            sa.String(36),
            sa.ForeignKey("diagnosis_results.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "episode_id",
            sa.String(36),
            sa.ForeignKey("diagnosis_episodes.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("issue_key", sa.String(64), nullable=False),
        sa.Column("error_type", sa.String(100), nullable=False),
        sa.Column("scope", sa.JSON(), nullable=False),
        sa.Column("evidence_keys", sa.JSON(), nullable=False),
        sa.Column("evidence_revision", sa.Integer()),
        sa.Column("observation_state", sa.String(30), nullable=False),
        sa.UniqueConstraint("diagnosis_result_id", "issue_key", name="uq_diagnosis_issue_key"),
    )
    for name in ("diagnosis_result_id", "episode_id"):
        op.create_index(f"ix_diagnosis_issues_{name}", "diagnosis_issues", [name])
    for table in ("diagnosis_feedback", "guidance_history"):
        op.add_column(table, sa.Column("episode_id", sa.String(36)))
        op.create_foreign_key(
            f"fk_{table}_episode",
            table,
            "diagnosis_episodes",
            ["episode_id"],
            ["id"],
            ondelete="RESTRICT",
        )
    op.create_index("ix_guidance_history_episode_id", "guidance_history", ["episode_id"])
    op.drop_constraint("uq_guidance_diagnosis_tree", "guidance_history", type_="unique")
    op.create_unique_constraint(
        "uq_guidance_diagnosis_tree_episode",
        "guidance_history",
        ["diagnosis_result_id", "fault_tree_id", "episode_id"],
    )
    op.create_index(
        "uq_guidance_legacy_tree",
        "guidance_history",
        ["diagnosis_result_id", "fault_tree_id"],
        unique=True,
        postgresql_where=sa.text("episode_id IS NULL"),
    )
    op.add_column("intervention_cases", sa.Column("episode_id", sa.String(36)))
    op.create_foreign_key(
        "fk_intervention_cases_episode",
        "intervention_cases",
        "diagnosis_episodes",
        ["episode_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.drop_constraint("uq_intervention_case_diagnosis", "intervention_cases", type_="unique")
    op.create_index(
        "uq_intervention_legacy_diagnosis",
        "intervention_cases",
        ["diagnosis_result_id"],
        unique=True,
        postgresql_where=sa.text("episode_id IS NULL"),
    )
    op.create_index(
        "uq_intervention_active_episode",
        "intervention_cases",
        ["episode_id"],
        unique=True,
        postgresql_where=sa.text(
            "episode_id IS NOT NULL AND status IN ('open','claimed','unconfirmed')"
        ),
    )


def downgrade():
    # New multi-problem records cannot be collapsed into a legacy unique
    # diagnosis key. Refuse destructive downgrade instead of deleting history.
    duplicates = (
        op.get_bind()
        .execute(
            sa.text(
                "SELECT 1 FROM intervention_cases GROUP BY diagnosis_result_id "
                "HAVING COUNT(*) > 1 LIMIT 1"
            )
        )
        .first()
    )
    guidance_duplicates = (
        op.get_bind()
        .execute(
            sa.text(
                "SELECT 1 FROM guidance_history GROUP BY diagnosis_result_id, fault_tree_id "
                "HAVING COUNT(*) > 1 LIMIT 1"
            )
        )
        .first()
    )
    if duplicates or guidance_duplicates:
        raise RuntimeError("multi-problem intervention history prevents a lossless downgrade")
    op.drop_index("uq_intervention_active_episode", table_name="intervention_cases")
    op.drop_index("uq_intervention_legacy_diagnosis", table_name="intervention_cases")
    op.create_unique_constraint(
        "uq_intervention_case_diagnosis", "intervention_cases", ["diagnosis_result_id"]
    )
    op.drop_constraint("fk_intervention_cases_episode", "intervention_cases", type_="foreignkey")
    op.drop_column("intervention_cases", "episode_id")
    op.drop_index("uq_guidance_legacy_tree", table_name="guidance_history")
    op.drop_constraint("uq_guidance_diagnosis_tree_episode", "guidance_history", type_="unique")
    op.create_unique_constraint(
        "uq_guidance_diagnosis_tree", "guidance_history", ["diagnosis_result_id", "fault_tree_id"]
    )
    for table in ("guidance_history", "diagnosis_feedback"):
        if table == "guidance_history":
            op.drop_index("ix_guidance_history_episode_id", table_name=table)
        op.drop_constraint(f"fk_{table}_episode", table, type_="foreignkey")
        op.drop_column(table, "episode_id")
    op.drop_table("diagnosis_issues")
    op.drop_index("ix_diagnosis_episodes_scope_key", table_name="diagnosis_episodes")
    op.drop_index("uq_active_problem_scope", table_name="diagnosis_episodes")
    op.drop_column("diagnosis_episodes", "scope_key")
    op.drop_column("diagnosis_results", "issue_model_version")
    op.drop_column("ai_usage_reservations", "attribution")
    op.drop_column("guidance_history", "help_wait_seconds")
