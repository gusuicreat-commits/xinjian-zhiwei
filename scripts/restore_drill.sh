#!/usr/bin/env sh
set -eu

if [ "$#" -ne 1 ] || [ ! -f "$1" ]; then
  echo "usage: scripts/restore_drill.sh /explicit/path/backup.dump" >&2
  exit 2
fi

backup_file=$1
drill_database="xinjian_restore_drill_$$"

cleanup() {
  docker compose exec -T postgres sh -c \
    'dropdb --if-exists -U "$POSTGRES_USER" "$1"' sh "$drill_database" >/dev/null
}
trap cleanup EXIT INT TERM

docker compose exec -T postgres sh -c \
  'createdb -U "$POSTGRES_USER" "$1"' sh "$drill_database"
docker compose exec -T postgres sh -c \
  'pg_restore --exit-on-error --no-owner --no-acl -U "$POSTGRES_USER" -d "$1"' \
  sh "$drill_database" <"$backup_file"

snapshot_sql='SELECT concat_ws(
  '"'"'|'"'"',
  (SELECT string_agg(version_num, '"'"','"'"' ORDER BY version_num) FROM alembic_version),
  (SELECT count(*) FROM devices),
  (SELECT count(*) FROM device_heartbeats),
  (SELECT count(*) FROM device_logs),
  (SELECT count(*) FROM sensor_readings),
  (SELECT count(*) FROM diagnosis_results),
  (SELECT count(*) FROM knowledge_documents),
  (SELECT count(*) FROM users),
  md5(concat_ws(
    '"'"'|'"'"',
    (SELECT coalesce(string_agg(id, '"'"','"'"' ORDER BY id), '"'"''"'"') FROM devices),
    (SELECT coalesce(string_agg(id, '"'"','"'"' ORDER BY id), '"'"''"'"') FROM diagnosis_results),
    (SELECT coalesce(string_agg(id, '"'"','"'"' ORDER BY id), '"'"''"'"') FROM knowledge_documents),
    (SELECT coalesce(string_agg(id, '"'"','"'"' ORDER BY id), '"'"''"'"') FROM users)
  ))
)'
source_snapshot=$(docker compose exec -T postgres sh -c \
  'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Atc "$1"' \
  sh "$snapshot_sql")
restored_snapshot=$(docker compose exec -T postgres sh -c \
  'psql -U "$POSTGRES_USER" -d "$1" -Atc "$2"' \
  sh "$drill_database" "$snapshot_sql")

if [ "$source_snapshot" != "$restored_snapshot" ]; then
  echo "restore verification mismatch" >&2
  echo "source:   $source_snapshot" >&2
  echo "restored: $restored_snapshot" >&2
  exit 1
fi

echo "restore snapshot: $restored_snapshot"
echo "isolated restore drill passed: $drill_database"
