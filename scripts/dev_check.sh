#!/usr/bin/env sh
set -eu

ROOT="$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

HOST="${DEV_HOST:-127.0.0.1}"
PORT="${DEV_PORT:-8124}"
PYTHON="${ROOT}/.venv/bin/python"
STARTED_HERE=0

if [ ! -x "$PYTHON" ]; then
  echo "run ./scripts/dev_up.sh first" >&2
  exit 1
fi

if ! "$PYTHON" -c "import urllib.request; urllib.request.urlopen('http://${HOST}:${PORT}/healthz', timeout=2).read()" >/dev/null 2>&1; then
  ./scripts/dev_up.sh
  STARTED_HERE=1
fi

"$PYTHON" -c "import json,urllib.request; body=json.load(urllib.request.urlopen('http://${HOST}:${PORT}/healthz')); raise SystemExit(0 if body['data']['status']=='ok' else 1)"
PYTHONPATH=. "$PYTHON" backend/test_local_server.py
PYTHONPATH=. "$PYTHON" backend/test_api.py
PYTHONPATH=. "$PYTHON" acceptance/run_cases.py

echo "local environment ok"

if [ "$STARTED_HERE" -eq 1 ]; then
  ./scripts/dev_down.sh
fi
