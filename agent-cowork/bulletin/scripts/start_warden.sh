#!/usr/bin/env bash
# start_warden.sh — 啟動 WSL 端 warden (背景)
# 用法： bash start_warden.sh
set -euo pipefail

REPO="$HOME/.openclaw/workspace-two/repos/agents-bulletin"
PIDFILE="$HOME/.openclaw/agent-cowork/warden.pid"
LOGFILE="$HOME/.openclaw/agent-cowork/warden.log"

# 若已跑就不重啟
if [ -f "$PIDFILE" ] && kill -0 "$(cat "$PIDFILE")" 2>/dev/null; then
  echo "warden already running, pid=$(cat "$PIDFILE")"
  exit 0
fi

cd "$REPO"
# log 由 warden.py 內部寫，不要 redirect 否則會重複
setsid nohup python3 scripts/warden.py > /dev/null 2>&1 < /dev/null &
WPID=$!
echo "$WPID" > "$PIDFILE"
disown || true
sleep 1

if kill -0 "$WPID" 2>/dev/null; then
  echo "✅ warden started, pid=$WPID"
  echo "   log: $LOGFILE"
  echo "   stop: bash $REPO/scripts/stop_warden.sh"
else
  echo "❌ warden failed to start, check $LOGFILE"
  tail -20 "$LOGFILE" || true
  exit 1
fi
