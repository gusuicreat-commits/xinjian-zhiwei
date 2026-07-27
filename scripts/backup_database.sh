#!/usr/bin/env sh
set -eu

if [ "$#" -ne 1 ]; then
  echo "usage: scripts/backup_database.sh /explicit/path/backup.dump" >&2
  exit 2
fi

backup_file=$1
case "$backup_file" in
  ""|"/") echo "refusing broad backup target" >&2; exit 2 ;;
esac

backup_parent=$(dirname "$backup_file")
if [ ! -d "$backup_parent" ]; then
  echo "backup parent does not exist: $backup_parent" >&2
  exit 2
fi
if [ -e "$backup_file" ]; then
  echo "backup target already exists; refusing overwrite: $backup_file" >&2
  exit 2
fi

docker compose exec -T postgres sh -c \
  'pg_dump -Fc --no-owner --no-acl -U "$POSTGRES_USER" "$POSTGRES_DB"' >"$backup_file"
echo "database backup created: $backup_file"
