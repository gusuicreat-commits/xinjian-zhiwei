"""bind every diagnosis thread to one student experiment session

Revision ID: 20260813_0020
Revises: 20260813_0019
Create Date: 2026-08-13
"""

from collections.abc import Sequence
from uuid import uuid4

import sqlalchemy as sa
from alembic import op

revision: str = "20260813_0020"
down_revision: str | None = "20260813_0019"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "experiment_sessions",
        sa.Column(
            "experiment_assignment_id",
            sa.String(36),
            sa.ForeignKey("experiment_assignments.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "student_user_id",
            sa.String(36),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "device_id",
            sa.String(36),
            sa.ForeignKey("devices.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True)),
        sa.Column("is_test_data", sa.Boolean(), nullable=False),
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
    )

    with op.batch_alter_table("diagnosis_workflow_runs") as batch_op:
        batch_op.add_column(sa.Column("student_user_id", sa.String(36), nullable=True))
        batch_op.add_column(sa.Column("experiment_session_id", sa.String(36), nullable=True))

    # Existing workflow rows can only be migrated when their device has exactly
    # one complete active binding. Never invent or guess a student/session scope.
    bind = op.get_bind()
    rows = bind.execute(
        sa.text(
            "SELECT id, device_id, created_at, is_test_data "
            "FROM diagnosis_workflow_runs ORDER BY created_at, id"
        )
    ).mappings()
    for row in rows:
        bindings = (
            bind.execute(
                sa.text(
                    "SELECT student_user_id, experiment_assignment_id "
                    "FROM device_bindings "
                    "WHERE device_id = :device_id AND is_active = true "
                    "AND student_user_id IS NOT NULL "
                    "AND experiment_assignment_id IS NOT NULL"
                ),
                {"device_id": row["device_id"]},
            )
            .mappings()
            .all()
        )
        if len(bindings) != 1:
            raise RuntimeError(
                "cannot migrate diagnosis workflow without exactly one active "
                "student/experiment/device binding"
            )
        session_id = str(uuid4())
        binding = bindings[0]
        bind.execute(
            sa.text(
                "INSERT INTO experiment_sessions "
                "(id, experiment_assignment_id, student_user_id, device_id, status, "
                "started_at, ended_at, is_test_data, created_at, updated_at) "
                "VALUES (:id, :assignment_id, :student_id, :device_id, 'completed', "
                ":started_at, :ended_at, :is_test_data, :created_at, :updated_at)"
            ),
            {
                "id": session_id,
                "assignment_id": binding["experiment_assignment_id"],
                "student_id": binding["student_user_id"],
                "device_id": row["device_id"],
                "started_at": row["created_at"],
                "ended_at": row["created_at"],
                "is_test_data": row["is_test_data"],
                "created_at": row["created_at"],
                "updated_at": row["created_at"],
            },
        )
        bind.execute(
            sa.text(
                "UPDATE diagnosis_workflow_runs "
                "SET student_user_id = :student_id, experiment_session_id = :session_id "
                "WHERE id = :workflow_id"
            ),
            {
                "student_id": binding["student_user_id"],
                "session_id": session_id,
                "workflow_id": row["id"],
            },
        )

    with op.batch_alter_table("diagnosis_workflow_runs") as batch_op:
        batch_op.alter_column("student_user_id", existing_type=sa.String(36), nullable=False)
        batch_op.alter_column("experiment_session_id", existing_type=sa.String(36), nullable=False)
        batch_op.create_foreign_key(
            "fk_diagnosis_workflow_runs_student_user_id",
            "users",
            ["student_user_id"],
            ["id"],
            ondelete="RESTRICT",
        )
        batch_op.create_foreign_key(
            "fk_diagnosis_workflow_runs_experiment_session_id",
            "experiment_sessions",
            ["experiment_session_id"],
            ["id"],
            ondelete="RESTRICT",
        )
        batch_op.create_check_constraint(
            "ck_diagnosis_workflow_thread_matches_diagnosis",
            "graph_thread_id = 'diagnosis:' || id",
        )
        batch_op.create_index(
            "ix_diagnosis_workflow_session_created",
            ["experiment_session_id", "created_at"],
        )

    # The experiment session tuple is the immutable authority for checkpoint
    # ownership. Prevent later reassignment of a session to another student,
    # assignment or device at the database boundary.
    if bind.dialect.name == "postgresql":
        op.execute(
            """
            CREATE FUNCTION prevent_experiment_session_scope_change()
            RETURNS trigger AS $$
            BEGIN
                IF NEW.student_user_id IS DISTINCT FROM OLD.student_user_id
                   OR NEW.device_id IS DISTINCT FROM OLD.device_id
                   OR NEW.experiment_assignment_id IS DISTINCT FROM OLD.experiment_assignment_id
                THEN
                    RAISE EXCEPTION 'experiment session ownership is immutable';
                END IF;
                RETURN NEW;
            END;
            $$ LANGUAGE plpgsql
            """
        )
        op.execute(
            """
            CREATE TRIGGER trg_experiment_session_scope_immutable
            BEFORE UPDATE ON experiment_sessions
            FOR EACH ROW EXECUTE FUNCTION prevent_experiment_session_scope_change()
            """
        )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute(
            "DROP TRIGGER IF EXISTS trg_experiment_session_scope_immutable ON experiment_sessions"
        )
        op.execute("DROP FUNCTION IF EXISTS prevent_experiment_session_scope_change()")
    with op.batch_alter_table("diagnosis_workflow_runs") as batch_op:
        batch_op.drop_index("ix_diagnosis_workflow_session_created")
        batch_op.drop_constraint("ck_diagnosis_workflow_thread_matches_diagnosis", type_="check")
        batch_op.drop_constraint(
            "fk_diagnosis_workflow_runs_experiment_session_id", type_="foreignkey"
        )
        batch_op.drop_constraint("fk_diagnosis_workflow_runs_student_user_id", type_="foreignkey")
        batch_op.drop_column("experiment_session_id")
        batch_op.drop_column("student_user_id")
    op.drop_table("experiment_sessions")
