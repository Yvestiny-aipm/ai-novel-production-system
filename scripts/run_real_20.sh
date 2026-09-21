#!/usr/bin/env sh
set -eu

ROOT="$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

is_ident() {
  printf '%s' "$1" | grep -Eq '^[A-Za-z_][A-Za-z0-9_]*$'
}

load_env_file() {
  env_file="$1"
  [ -f "$env_file" ] || return 0
  while IFS= read -r line || [ -n "$line" ]; do
    case "$line" in
      ''|\#*) continue ;;
      export\ *) line="${line#export }" ;;
    esac
    case "$line" in
      *=*)
        key="${line%%=*}"
        value="${line#*=}"
        is_ident "$key" || continue
        eval "already=\${$key-}"
        if [ -z "$already" ]; then
          export "$key=$value"
        fi
        ;;
    esac
  done < "$env_file"
}

load_env_file "$ROOT/.env"

export RUN_REAL_MODEL=1
export EXECUTION_MODE="${EXECUTION_MODE:-sequential}"
export REAL_TEST_SCENE_COUNT=20
export REAL_TEST_AUTO_CONFIRM=1
export REAL_TEST_DB="${REAL_TEST_DB:-$ROOT/data/real_test_20_b.db}"
export WRITING_PROVIDER="${WRITING_PROVIDER:-deepseek}"
export PYTHONUNBUFFERED=1

PYTHON="${ROOT}/.venv/bin/python"
if [ ! -x "$PYTHON" ]; then
  echo "run ./scripts/dev_up.sh first so .venv exists" >&2
  exit 1
fi

mkdir -p "$ROOT/data"
echo "real 20-scene test db=$REAL_TEST_DB (path only; secrets stay in env)"
exec "$PYTHON" integration/run_real_test.py
