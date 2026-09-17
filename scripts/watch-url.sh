#!/bin/bash
# ============================================================
# watch-url.sh - 監聽 stream.env 是否被手動填入 URL
# 建立：2026-09-15 by 大寶
#
# 情境：auto-grab 失敗 → 大大在 TG 貼 m3u8
#       agent 在 chat 寫 m3u8 後會寫到 stream.env
#       這個腳本每 30 秒檢查一次,如果 STREAM_URL 不為空就觸發 start.sh
#
# 用法：在 23:25 跟 auto-grab 一起啟動,跑最多 10 分鐘（到 23:35）
# 結束條件：URL 填好且 start.sh 成功 / 或超過 10 分鐘
# ============================================================

set -u

BASE_DIR="/mnt/d/record-loop"
ENV_FILE="$BASE_DIR/run/stream.env"
LOG_FILE="$BASE_DIR/logs/watch-url.log"
MAX_WAIT_SEC=600   # 10 分鐘
INTERVAL=10

mkdir -p "$(dirname "$LOG_FILE")"

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$LOG_FILE"; }

log "===== watch-url 啟動,最長等 $MAX_WAIT_SEC 秒 ====="

START_TS=$(date +%s)
while true; do
    NOW=$(date +%s)
    ELAPSED=$((NOW - START_TS))

    if [ "$ELAPSED" -ge "$MAX_WAIT_SEC" ]; then
        log "⏱️ 超過 $MAX_WAIT_SEC 秒,放棄等待"
        exit 1
    fi

    # 讀 STREAM_URL（去引號 + trim）
    URL=$(grep '^STREAM_URL=' "$ENV_FILE" 2>/dev/null | sed 's/^STREAM_URL=//' | tr -d '"' | xargs)

    if [ -n "$URL" ] && [ "$URL" != "" ]; then
        log "✅ STREAM_URL 已填: $URL"
        log "→ 觸發 start.sh"
        bash "$BASE_DIR/bin/start.sh" 2>&1 | tee -a "$LOG_FILE"
        if [ -f "$BASE_DIR/run/recorder.pid" ] && kill -0 "$(cat "$BASE_DIR/run/recorder.pid")" 2>/dev/null; then
            log "✅ 錄影已啟動,watch-url 任務結束"
            exit 0
        else
            log "❌ start.sh 沒成功啟動"
            exit 2
        fi
    fi

    sleep "$INTERVAL"
done