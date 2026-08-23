#!/usr/bin/env bash
# stop_warden.sh — 停止 warden
set -euo pipefail
PIDFILE="$HOME/.openclaw/agent-cowork/warden.pid"
if [ ! -f "$PIDFILE" ]; then
  echo "no pidfile, nothing to stop"; exit 0
fi
PID="$(cat "$PIDFILE")"
if kill -0 "$PID" 2>/dev/null; then
  kill "$PID"
  sleep 1
  if kill -0 "$PID" 2>/dev/null; then
    kill -9 "$PID" || true
  fi
  echo "✅ warden stopped (pid=$PID)"
else
  echo "warden pid=$PID already not running"
fi
rm -f "$PIDFILE"
