"""Prepare only the explicitly selected evaluation database; never use DATABASE_URL.

Historical migrations require pgvector even though diagnosis does not use vectors.
Keep the extension in public so dropping an evaluation schema cannot remove it.
"""

import os
import sys


def main():
    dsn = os.environ.get("XINJIAN_EVAL_POSTGRES_DSN")
    if not dsn:
        print("XINJIAN_EVAL_POSTGRES_DSN must select an isolated test database.", file=sys.stderr)
        return 2

    import psycopg

    try:
        with psycopg.connect(dsn, autocommit=True, connect_timeout=5) as db:
            db.execute("CREATE EXTENSION IF NOT EXISTS vector WITH SCHEMA public")
            namespace = db.execute(
                "SELECT n.nspname FROM pg_extension e "
                "JOIN pg_namespace n ON n.oid = e.extnamespace WHERE e.extname = 'vector'"
            ).fetchone()
            if namespace != ("public",):
                print(
                    "The isolated test database must have the vector extension in public; "
                    "use a fresh test database or move its extension before verification.",
                    file=sys.stderr,
                )
                return 1
    except psycopg.Error as exc:
        # Connection errors can contain endpoint details; never print the DSN or credentials.
        print(f"Evaluation PostgreSQL preparation failed ({type(exc).__name__}).", file=sys.stderr)
        return 1

    print("Isolated evaluation PostgreSQL extension is ready in public.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
