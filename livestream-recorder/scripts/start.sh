#!/bin/bash
# ============================================================
# start.sh - 啟動錄影 daemon
# 用法：./start.sh
# 特性：
#   - setsid + nohup 完全脫離終端機
#   - 寫 PID 檔方便管理
#   - 自動避免重複啟動
# ============================================================

set -u

BASE_DIR="/mnt/d/record-loop"
PID_FILE="$BASE_DIR/run/recorder.pid"
LOG_FILE="$BASE_DIR/logs/recorder.out.log"

# 檢查是否已在跑
if [ -f "$PID_FILE" ]; then
    OLD_PID=$(cat "$PID_FILE")
    if kill -0 "$OLD_PID" 2>/dev/null; then
        echo "❌ 錄影已在跑（PID $OLD_PID）"
        echo "   要重啟請先跑 ./stop.sh"
        exit 1
    else
        echo "⚠️ 殘留 PID $OLD_PID（已死），清掉"
        rm -f "$PID_FILE"
    fi
fi

# 檢查 stream.env
ENV_FILE="$BASE_DIR/run/stream.env"
if [ ! -f "$ENV_FILE" ]; then
    echo "❌ 找不到 $ENV_FILE"
    echo "   請先建立並填入 STREAM_URL"
    echo "   範例：cp $BASE_DIR/run/stream.env.example $ENV_FILE"
    exit 1
fi

# 啟動（完全脫離）
cd "$BASE_DIR"
setsid nohup "$BASE_DIR/bin/record-loop.sh" > "$LOG_FILE" 2>&1 < /dev/null &
NEW_PID=$!
disown 2>/dev/null || true
echo "$NEW_PID" > "$PID_FILE"

sleep 2
if kill -0 "$NEW_PID" 2>/dev/null; then
    echo "✅ 錄影已啟動"
    echo "   PID: $NEW_PID"
    echo "   日誌: $LOG_FILE"
    echo "   停止: ./stop.sh"
    echo "   狀態: ./status.sh"
else
    echo "❌ 啟動失敗，看 $LOG_FILE"
    rm -f "$PID_FILE"
    exit 1
fi