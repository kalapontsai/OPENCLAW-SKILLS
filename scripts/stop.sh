#!/bin/bash
# ============================================================
# stop.sh - 停止錄影 daemon
# 用法：./stop.sh
# ============================================================

set -u

BASE_DIR="/mnt/d/record-loop"
PID_FILE="$BASE_DIR/run/recorder.pid"

if [ ! -f "$PID_FILE" ]; then
    echo "⚠️ 沒有 PID 檔，本來就沒在跑"
    exit 0
fi

PID=$(cat "$PID_FILE")
if kill -0 "$PID" 2>/dev/null; then
    kill -TERM "$PID"
    sleep 2
    if kill -0 "$PID" 2>/dev/null; then
        echo "⚠️ SIGTERM 沒用，送 SIGKILL"
        kill -KILL "$PID"
    fi
    echo "✅ 錄影已停止（PID $PID）"
else
    echo "⚠️ PID $PID 已死，清檔"
fi
rm -f "$PID_FILE"