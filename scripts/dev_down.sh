#!/usr/bin/env sh
set -eu

ROOT="$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)"
PIDFILE="${DEV_PIDFILE:-$ROOT/data/dev.pid}"

if [ ! -f "$PIDFILE" ]; then
  echo "not running"
  exit 0
fi

pid="$(cat "$PIDFILE")"
if kill -0 "$pid" 2>/dev/null; then
  kill "$pid"
  i=0
  while [ "$i" -lt 20 ] && kill -0 "$pid" 2>/dev/null; do
    sleep 0.1
    i=$((i + 1))
  done
  if kill -0 "$pid" 2>/dev/null; then
    kill -9 "$pid" 2>/dev/null || true
  fi
  echo "stopped pid=$pid"
else
  echo "stale pid file"
fi
rm -f "$PIDFILE"
