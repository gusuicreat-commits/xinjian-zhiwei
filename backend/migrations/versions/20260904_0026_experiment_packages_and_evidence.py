"""Add versioned experiment packages and normalized diagnosis evidence.

Revision ID: 20260904_0026
Revises: 20260902_0025
Create Date: 2026-09-04
"""

from collections.abc import Sequence
from typing import Optional, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20260904_0026"
down_revision: Optional[str] = "20260902_0025"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "experiments",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("code", sa.String(length=100), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("category", sa.String(length=100), nullable=False),
        sa.Column("locale", sa.String(length=20), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("is_test_data", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_experiments_code", "experiments", ["code"], unique=True)

    op.create_table(
        "experiment_versions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("experiment_id", sa.String(length=36), nullable=False),
        sa.Column("version", sa.String(length=50), nullable=False),
        sa.Column("schema_version", sa.String(length=20), nullable=False),
        sa.Column("engine_compatibility", sa.String(length=100), nullable=False),
        sa.Column("package_hash", sa.String(length=64), nullable=False),
        sa.Column("package_manifest", sa.JSON(), nullable=False),
        sa.Column("package_content", sa.JSON(), nullable=False),
        sa.Column("validation_report", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("is_current", sa.Boolean(), nullable=False),
        sa.Column("created_by_user_id", sa.String(length=36), nullable=False),
        sa.Column("reviewed_by_user_id", sa.String(length=36)),
        sa.Column("published_at", sa.DateTime(timezone=True)),
        sa.Column("is_test_data", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["experiment_id"], ["experiments.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["reviewed_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("experiment_id", "version", name="uq_experiment_versions_pair"),
        sa.UniqueConstraint("id", "experiment_id", name="uq_experiment_versions_id_experiment"),
        sa.UniqueConstraint("package_hash"),
    )
    op.create_index(
        "ix_experiment_versions_status_published",
        "experiment_versions",
        ["status", "published_at"],
    )

    op.create_table(
        "experiment_package_artifacts",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("experiment_version_id", sa.String(length=36), nullable=False),
        sa.Column("kind", sa.String(length=50), nullable=False),
        sa.Column("artifact_key", sa.String(length=200), nullable=False),
        sa.Column("content_json", sa.JSON(), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("source_path", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["experiment_version_id"], ["experiment_versions.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "experiment_version_id",
            "kind",
            "artifact_key",
            name="uq_experiment_package_artifact",
        ),
    )
    op.create_index(
        "ix_experiment_package_artifacts_version_kind",
        "experiment_package_artifacts",
        ["experiment_version_id", "kind"],
    )

    with op.batch_alter_table("experiment_assignments") as batch_op:
        batch_op.add_column(sa.Column("experiment_version_id", sa.String(length=36)))
        batch_op.create_foreign_key(
            "fk_experiment_assignments_package_version",
            "experiment_versions",
            ["experiment_version_id"],
            ["id"],
            ondelete="RESTRICT",
        )

    for table in ("diagnosis_results", "diagnosis_workflow_runs"):
        with op.batch_alter_table(table) as batch_op:
            batch_op.add_column(sa.Column("experiment_record_id", sa.String(length=36)))
            batch_op.add_column(sa.Column("experiment_version_id", sa.String(length=36)))
            batch_op.create_foreign_key(
                f"fk_{table}_experiment",
                "experiments",
                ["experiment_record_id"],
                ["id"],
                ondelete="RESTRICT",
            )
            batch_op.create_foreign_key(
                f"fk_{table}_experiment_version_scope",
                "experiment_versions",
                ["experiment_version_id", "experiment_record_id"],
                ["id", "experiment_id"],
                ondelete="RESTRICT",
            )
            batch_op.create_index(
                f"ix_{table}_experiment_version_id",
                ["experiment_version_id"],
            )

    with op.batch_alter_table("diagnosis_workflow_runs") as batch_op:
        batch_op.add_column(
            sa.Column("state_revision", sa.Integer(), nullable=False, server_default="0")
        )
        batch_op.alter_column("state_revision", server_default=None)

    op.create_table(
        "diagnosis_evidence",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("diagnosis_id", sa.String(length=36), nullable=False),
        sa.Column("experiment_record_id", sa.String(length=36)),
        sa.Column("experiment_version_id", sa.String(length=36)),
        sa.Column("evidence_type", sa.String(length=100), nullable=False),
        sa.Column("source_type", sa.String(length=50), nullable=False),
        sa.Column("source_ref", sa.String(length=200), nullable=False),
        sa.Column("normalized_value", sa.JSON(), nullable=False),
        sa.Column("raw_payload", sa.JSON(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["diagnosis_id"], ["diagnosis_results.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["experiment_record_id"], ["experiments.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["experiment_version_id", "experiment_record_id"],
            ["experiment_versions.id", "experiment_versions.experiment_id"],
            name="fk_diagnosis_evidence_experiment_version_scope",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "diagnosis_id",
            "evidence_type",
            "source_type",
            "source_ref",
            name="uq_diagnosis_evidence_source",
        ),
    )
    op.create_index(
        "ix_diagnosis_evidence_diagnosis_time",
        "diagnosis_evidence",
        ["diagnosis_id", "occurred_at"],
    )
    op.create_index(
        "ix_diagnosis_evidence_experiment_type",
        "diagnosis_evidence",
        ["experiment_record_id", "evidence_type"],
    )


def downgrade() -> None:
    op.drop_index("ix_diagnosis_evidence_experiment_type", table_name="diagnosis_evidence")
    op.drop_index("ix_diagnosis_evidence_diagnosis_time", table_name="diagnosis_evidence")
    op.drop_table("diagnosis_evidence")

    with op.batch_alter_table("diagnosis_workflow_runs") as batch_op:
        batch_op.drop_column("state_revision")

    for table in ("diagnosis_workflow_runs", "diagnosis_results"):
        with op.batch_alter_table(table) as batch_op:
            batch_op.drop_index(f"ix_{table}_experiment_version_id")
            batch_op.drop_constraint(f"fk_{table}_experiment_version_scope", type_="foreignkey")
            batch_op.drop_constraint(f"fk_{table}_experiment", type_="foreignkey")
            batch_op.drop_column("experiment_version_id")
            batch_op.drop_column("experiment_record_id")

    with op.batch_alter_table("experiment_assignments") as batch_op:
        batch_op.drop_constraint("fk_experiment_assignments_package_version", type_="foreignkey")
        batch_op.drop_column("experiment_version_id")

    op.drop_index(
        "ix_experiment_package_artifacts_version_kind",
        table_name="experiment_package_artifacts",
    )
    op.drop_table("experiment_package_artifacts")
    op.drop_index("ix_experiment_versions_status_published", table_name="experiment_versions")
    op.drop_table("experiment_versions")
    op.drop_index("ix_experiments_code", table_name="experiments")
    op.drop_table("experiments")
