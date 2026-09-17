#!/usr/bin/env sh
set -eu
DB_PATH="${1:-./data/novel.db}"
mkdir -p "$(dirname "$DB_PATH")"
sqlite3 "$DB_PATH" < "$(dirname "$0")/migrations/001_initial.sql"
echo "initialized $DB_PATH"
