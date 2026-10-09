"""0040: actual upgrade/downgrade and metadata in explicit isolated PostgreSQL."""

from sqlalchemy import MetaData, Table, inspect, text
from test_migration_r2 import _seed
from test_migration_r2 import migration_db as source_migration_fixture

migration_db = source_migration_fixture


def test_query_receipt_upgrade_downgrade_preserves_old_business_rows(migration_db):
    engine, migrate = migration_db
    migrate("upgrade", "20261003_0039")
    with engine.begin() as conn:
        user = _seed(conn, "users")
        device = _seed(conn, "devices")
        course = _seed(conn, "courses")
        classroom = _seed(conn, "classes", course_id=course["id"])
        assignment = _seed(conn, "experiment_assignments", class_id=classroom["id"])
        session = _seed(
            conn,
            "experiment_sessions",
            device_id=device["id"],
            student_user_id=user["id"],
            experiment_assignment_id=assignment["id"],
        )
        diagnosis = _seed(conn, "diagnosis_results", device_id=device["id"])
    migrate("upgrade", "head")
    migrate("check")
    with engine.begin() as conn:
        assert conn.scalar(text("SELECT version_num FROM alembic_version")) == "20261009_0040"
        task = _seed(conn, "query_tasks", session_id=session["id"], diagnosis_id=diagnosis["id"])
        question = _seed(conn, "query_questions", task_id=task["id"])
        _seed(
            conn,
            "query_answer_receipts",
            task_id=task["id"],
            question_record_id=question["id"],
            submitted_by_user_id=user["id"],
            value="unclear",
        )
    migrate("downgrade", "20261003_0039")
    with engine.connect() as conn:
        assert "query_tasks" not in inspect(conn).get_table_names()
        for name, original in (
            ("users", user),
            ("experiment_sessions", session),
            ("diagnosis_results", diagnosis),
        ):
            table = Table(name, MetaData(), autoload_with=conn)
            assert (
                dict(
                    conn.execute(table.select().where(table.c.id == original["id"]))
                    .mappings()
                    .one()
                )
                == original
            )
    migrate("upgrade", "head")
    migrate("check")
