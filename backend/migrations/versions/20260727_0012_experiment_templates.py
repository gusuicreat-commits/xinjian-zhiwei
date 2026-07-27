"""versioned experiment templates and diagnostic artifacts

Revision ID: 20260727_0012
Revises: 20260727_0011
"""

import sqlalchemy as sa
from alembic import op

revision = "20260727_0012"
down_revision = "20260727_0011"
branch_labels = None
depends_on = None


def _identity_columns() -> list[sa.Column]:
    return [
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    ]


def upgrade() -> None:
    op.create_table(
        "experiment_templates",
        sa.Column("code", sa.String(100), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("description", sa.String(1000)),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("is_test_data", sa.Boolean(), nullable=False),
        *_identity_columns(),
    )
    op.create_index(
        "ix_experiment_templates_code",
        "experiment_templates",
        ["code"],
        unique=True,
    )
    op.create_table(
        "experiment_template_versions",
        sa.Column(
            "template_id",
            sa.String(36),
            sa.ForeignKey("experiment_templates.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("version", sa.String(50), nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("content", sa.JSON(), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("missing_fields", sa.JSON(), nullable=False),
        sa.Column(
            "created_by_user_id",
            sa.String(36),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "reviewed_by_user_id",
            sa.String(36),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
        ),
        sa.Column("published_at", sa.DateTime(timezone=True)),
        *_identity_columns(),
        sa.UniqueConstraint(
            "template_id",
            "version",
            name="uq_template_versions_pair",
        ),
    )
    op.create_table(
        "diagnostic_artifacts",
        sa.Column("kind", sa.String(30), nullable=False),
        sa.Column("code", sa.String(100), nullable=False),
        sa.Column("version", sa.String(50), nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("definition", sa.JSON(), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("is_test_data", sa.Boolean(), nullable=False),
        *_identity_columns(),
        sa.UniqueConstraint(
            "kind",
            "code",
            "version",
            name="uq_diagnostic_artifact_version",
        ),
    )
    op.create_foreign_key(
        "fk_experiment_assignments_template_version",
        "experiment_assignments",
        "experiment_template_versions",
        ["template_version_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.add_column(
        "experiment_assignments",
        sa.Column("rule_artifact_id", sa.String(36)),
    )
    op.add_column(
        "experiment_assignments",
        sa.Column("fault_tree_artifact_id", sa.String(36)),
    )
    op.create_foreign_key(
        "fk_experiment_assignments_rule_artifact",
        "experiment_assignments",
        "diagnostic_artifacts",
        ["rule_artifact_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_experiment_assignments_fault_tree_artifact",
        "experiment_assignments",
        "diagnostic_artifacts",
        ["fault_tree_artifact_id"],
        ["id"],
        ondelete="RESTRICT",
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_experiment_assignments_fault_tree_artifact",
        "experiment_assignments",
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_experiment_assignments_rule_artifact",
        "experiment_assignments",
        type_="foreignkey",
    )
    op.drop_column("experiment_assignments", "fault_tree_artifact_id")
    op.drop_column("experiment_assignments", "rule_artifact_id")
    op.drop_constraint(
        "fk_experiment_assignments_template_version",
        "experiment_assignments",
        type_="foreignkey",
    )
    op.drop_table("diagnostic_artifacts")
    op.drop_table("experiment_template_versions")
    op.drop_table("experiment_templates")
