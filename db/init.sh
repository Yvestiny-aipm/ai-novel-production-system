#!/usr/bin/env sh
set -eu
DB_PATH="${1:-./data/novel.db}"
mkdir -p "$(dirname "$DB_PATH")"
for migration in "$(dirname "$0")"/migrations/*.sql; do
  version="$(basename "$migration" .sql)"
  applied="$(sqlite3 "$DB_PATH" "SELECT 1 FROM sqlite_master WHERE type='table' AND name='schema_migrations';")"
  if [ "$applied" != "1" ] || [ "$(sqlite3 "$DB_PATH" "SELECT 1 FROM schema_migrations WHERE version='$version';")" != "1" ]; then
    sqlite3 "$DB_PATH" < "$migration"
  fi
done
echo "initialized $DB_PATH"
