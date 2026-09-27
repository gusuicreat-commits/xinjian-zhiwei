"""Snapshot-consistent PostgreSQL backup and disposable restore verification.

Uses the configured Compose postgres service, or --container for an isolated test
container. No business process is started and no running database is migrated.
"""

import argparse
import hashlib
import json
import os
import select
import subprocess
import time
from pathlib import Path
from uuid import uuid4


def pg_command(container, executable, database="", *args):
    # POSIX sh has no ${@:3}; shift keeps all values separate and quoted.
    prefix = (
        ["docker", "exec", "-i", container]
        if container
        else ["docker", "compose", "exec", "-T", "postgres"]
    )
    return prefix + [
        "sh",
        "-c",
        'tool=$1; db=${2:-$POSTGRES_DB}; shift 2; exec "$tool" -U "$POSTGRES_USER" -d "$db" "$@"',
        "sh",
        executable,
        database,
        *args,
    ]


class SQL:
    def __init__(self, container=None, database=""):
        self.process = subprocess.Popen(
            pg_command(
                container, "psql", database, "-X", "-qAt", "-v", "ON_ERROR_STOP=1"
            ),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )

    def query(self, query):
        marker = "__complete_" + uuid4().hex
        self.process.stdin.write((query + ";\nSELECT '" + marker + "';\n").encode())
        self.process.stdin.flush()
        output = bytearray()
        deadline = time.monotonic() + 300
        while time.monotonic() < deadline:
            ready, _, _ = select.select([self.process.stdout], [], [], 1)
            if not ready:
                if self.process.poll() is not None:
                    raise RuntimeError("PostgreSQL command failed")
                continue
            chunk = os.read(self.process.stdout.fileno(), 65536)
            if not chunk:
                raise RuntimeError(
                    "PostgreSQL command ended before verification completed"
                )
            output.extend(chunk)
            suffix = (marker + "\n").encode()
            if output.endswith(suffix):
                return output[: -len(suffix)].decode().strip()
        raise RuntimeError("PostgreSQL verification timed out")

    def close(self):
        if self.process.poll() is None:
            self.process.stdin.close()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait()


def quote(identifier):
    return '"' + identifier.replace('"', '""') + '"'


def manifest(sql):
    names = json.loads(
        sql.query(
            "SELECT coalesce(json_agg(row_to_json(t)), '[]') FROM (SELECT schemaname, tablename FROM pg_tables WHERE schemaname NOT IN ('pg_catalog','information_schema') AND schemaname NOT LIKE 'pg_toast%' ORDER BY schemaname, tablename) t"
        )
    )
    tables = {}
    for row in names:
        table = quote(row["schemaname"]) + "." + quote(row["tablename"])
        # Hash every stored column (including relation IDs and JSON), preserving duplicates.
        summary = sql.query(
            f"SELECT json_build_object('rows', count(*), 'sha256', encode(sha256(convert_to(coalesce(string_agg(digest, '' ORDER BY digest), ''), 'UTF8')), 'hex')) FROM (SELECT encode(sha256(convert_to(to_jsonb(t)::text, 'UTF8')), 'hex') AS digest FROM {table} t) hashes"
        )
        tables[row["schemaname"] + "." + row["tablename"]] = json.loads(summary)
    structure = sql.query(
        "SELECT coalesce(json_agg(row_to_json(c)), '[]') FROM (SELECT n.nspname AS schema, r.relname AS table, a.attname AS column, format_type(a.atttypid, a.atttypmod) AS type, a.attnotnull AS not_null FROM pg_attribute a JOIN pg_class r ON r.oid=a.attrelid JOIN pg_namespace n ON n.oid=r.relnamespace WHERE r.relkind IN ('r','p') AND a.attnum>0 AND NOT a.attisdropped AND n.nspname NOT IN ('pg_catalog','information_schema') AND n.nspname NOT LIKE 'pg_toast%' ORDER BY 1,2,a.attnum) c"
    )
    constraints = sql.query(
        "SELECT coalesce(json_agg(row_to_json(c)), '[]') FROM (SELECT n.nspname AS schema, r.relname AS table, c.conname AS name, c.convalidated AS validated, pg_get_constraintdef(c.oid) AS definition FROM pg_constraint c JOIN pg_class r ON r.oid=c.conrelid JOIN pg_namespace n ON n.oid=r.relnamespace WHERE n.nspname NOT IN ('pg_catalog','information_schema') AND n.nspname NOT LIKE 'pg_toast%' ORDER BY 1,2,3) c"
    )
    return {
        "tables": tables,
        "columns": json.loads(structure),
        "constraints": json.loads(constraints),
    }


def file_hash(path):
    with path.open("rb") as source:
        digest = hashlib.sha256()
        for chunk in iter(lambda: source.read(1024 * 1024), b''):
            digest.update(chunk)
        return digest.hexdigest()


def backup(path, container=None, database=""):
    sidecar = Path(str(path) + ".manifest.json")
    if path.exists() or sidecar.exists() or not path.parent.is_dir():
        raise ValueError(
            "backup and manifest targets must be new files in an existing directory"
        )
    sql = SQL(container, database)
    created = False
    try:
        sql.query("BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY")
        snapshot = sql.query("SELECT pg_export_snapshot()")
        expected = manifest(sql)
        with path.open("xb") as out:
            created = True
            os.chmod(path, 0o600)
            subprocess.run(
                pg_command(
                    container,
                    "pg_dump",
                    database,
                    "-Fc",
                    "--no-owner",
                    "--no-acl",
                    "--snapshot=" + snapshot,
                ),
                stdout=out,
                check=True,
            )
        sql.query("COMMIT")
        with sidecar.open("x", encoding="utf-8") as out:
            os.chmod(sidecar, 0o600)
            json.dump(
                {
                    "format": 1,
                    "dump_sha256": file_hash(path),
                    "scope": "this database only; a separate checkpoint database requires a coordinated backup during paused writes",
                    "snapshot": expected,
                },
                out,
                ensure_ascii=False,
                indent=2,
            )
    except BaseException:
        if created:
            path.unlink(missing_ok=True)
        raise
    finally:
        sql.close()
    print(f"Backup and snapshot manifest saved: {path}")


def verify(path, sql):
    expected = json.loads(Path(str(path) + ".manifest.json").read_text())
    if expected["format"] != 1 or file_hash(path) != expected["dump_sha256"]:
        raise ValueError("backup digest/manifest format mismatch")
    actual = manifest(sql)
    if actual != expected["snapshot"]:
        # Do not print record bodies, credentials, or private values.
        different = sorted(
            name
            for name in set(actual["tables"]) | set(expected["snapshot"]["tables"])
            if actual["tables"].get(name) != expected["snapshot"]["tables"].get(name)
        )
        raise ValueError(
            "restored content or relationships differ; tables: " + ", ".join(different)
        )
    return len(actual["tables"])


def restore_drill(path, container=None):
    expected = json.loads(Path(str(path) + ".manifest.json").read_text())
    if file_hash(path) != expected["dump_sha256"]:
        raise ValueError("backup digest mismatch")
    database = "xinjian_restore_drill_" + uuid4().hex
    control = SQL(container)
    restored = None
    created = False
    try:
        control.query("CREATE DATABASE " + quote(database))
        created = True
        with path.open("rb") as source:
            subprocess.run(
                pg_command(
                    container,
                    "pg_restore",
                    database,
                    "--exit-on-error",
                    "--no-owner",
                    "--no-acl",
                ),
                stdin=source,
                check=True,
            )
        restored = SQL(container, database)
        restored.query("BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY")
        count = verify(path, restored)
        print(
            f"Isolated restore verified: {count} tables, all row contents, columns and constraints. Scope: this database only."
        )
    finally:
        if restored:
            restored.close()
        if created:
            control.query("DROP DATABASE " + quote(database))
        control.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=["backup", "restore"])
    parser.add_argument("path", type=Path)
    parser.add_argument(
        "--container", help="explicit PostgreSQL container; default Compose postgres"
    )
    parser.add_argument(
        "--database", default="", help="source database for backup only"
    )
    args = parser.parse_args()
    if args.operation == "backup":
        backup(args.path, args.container, args.database)
    else:
        if args.database:
            parser.error("restore always creates a disposable database")
        restore_drill(args.path, args.container)


if __name__ == "__main__":
    main()
