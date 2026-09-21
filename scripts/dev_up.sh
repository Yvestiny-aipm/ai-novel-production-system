#!/usr/bin/env sh
set -eu

ROOT="$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

PIDFILE="${DEV_PIDFILE:-$ROOT/data/dev.pid}"
LOGFILE="${DEV_LOGFILE:-$ROOT/data/dev.log}"
FOREGROUND=0

for arg in "$@"; do
  case "$arg" in
    --fg|--foreground) FOREGROUND=1 ;;
    --help|-h)
      echo "usage: ./scripts/dev_up.sh [--fg]"
      echo "Start the local API and frontend on one port. Keys stay in the environment or .env."
      exit 0
      ;;
    *)
      echo "unknown argument: $arg" >&2
      exit 2
      ;;
  esac
done

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

require_cmd() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "missing command: $1" >&2
    exit 1
  fi
}

require_cmd python3
python3 -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)' || {
  echo "Python 3.11+ is required" >&2
  exit 1
}

load_env_file "$ROOT/.env"

HOST="${DEV_HOST:-127.0.0.1}"
PORT="${DEV_PORT:-8124}"
DB_PATH="${NOVEL_DB:-$ROOT/data/local.db}"
PYTHON="${ROOT}/.venv/bin/python"

if [ ! -x "$PYTHON" ]; then
  python3 -m venv "$ROOT/.venv"
fi
"$PYTHON" -m pip install -q -r "$ROOT/requirements.txt"

mkdir -p "$ROOT/data" "$(dirname "$DB_PATH")"

health_url="http://${HOST}:${PORT}/healthz"
if [ -f "$PIDFILE" ]; then
  old_pid="$(cat "$PIDFILE")"
  if kill -0 "$old_pid" 2>/dev/null; then
    if "$PYTHON" -c "import urllib.request; urllib.request.urlopen('$health_url', timeout=2).read()" >/dev/null 2>&1; then
      echo "already running pid=$old_pid"
      echo "workbench  http://${HOST}:${PORT}/"
      echo "admin      http://${HOST}:${PORT}/admin.html"
      echo "health     $health_url"
      exit 0
    fi
  fi
  rm -f "$PIDFILE"
fi

if [ "$FOREGROUND" -eq 1 ]; then
  exec "$PYTHON" -m backend.local_server --db "$DB_PATH" --host "$HOST" --port "$PORT"
fi

"$PYTHON" -m backend.local_server \
  --daemon \
  --db "$DB_PATH" \
  --host "$HOST" \
  --port "$PORT" \
  --pidfile "$PIDFILE" \
  --logfile "$LOGFILE"

i=0
while [ "$i" -lt 25 ]; do
  if "$PYTHON" -c "import urllib.request; urllib.request.urlopen('$health_url', timeout=1).read()" >/dev/null 2>&1; then
    echo "started pid=$(cat "$PIDFILE")"
    echo "workbench  http://${HOST}:${PORT}/"
    echo "admin      http://${HOST}:${PORT}/admin.html"
    echo "health     $health_url"
    echo "db         local file under data/ (not printed)"
    echo "log        $LOGFILE"
    exit 0
  fi
  i=$((i + 1))
  sleep 0.2
done

echo "failed to become healthy; see $LOGFILE" >&2
exit 1
