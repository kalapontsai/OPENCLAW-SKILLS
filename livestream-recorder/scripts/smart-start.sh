#!/bin/bash
# ============================================================
# smart-start.sh - 條件式啟動錄影（23:30 cron 跑這個）
# 建立：2026-09-15 by 大寶
#
# 邏輯：
#   1. 讀 stream.env 的 STREAM_URL
#   2. 空 → 沒抓到,跑 fallback TG 通知,exit 1
#   3. 不空 → 跑 start.sh
#   4. 啟動成功 → 心跳確認,exit 0
#   5. 啟動失敗 → TG 通知,exit 2
# ============================================================

set -u

BASE_DIR="/mnt/d/record-loop"
ENV_FILE="$BASE_DIR/run/stream.env"
LOG_FILE="$BASE_DIR/logs/smart-start.log"

mkdir -p "$(dirname "$LOG_FILE")"

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$LOG_FILE"; }

notify_tg() {
    local msg="$1"
    if [ -n "${TG_CHAT_ID:-}" ] && [ -n "${TELEGRAM_BOT_TOKEN:-}" ]; then
        curl -s -X POST "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage" \
            -d "chat_id=$TG_CHAT_ID" \
            -d "text=$msg" \
            -d "parse_mode=Markdown" >> "$LOG_FILE" 2>&1
    fi
    log "TG: $msg"
}

URL=$(grep '^STREAM_URL=' "$ENV_FILE" 2>/dev/null | sed 's/^STREAM_URL=//' | tr -d '"' | xargs)

log "===== smart-start 啟動 ====="
log "STREAM_URL='$URL'"

if [ -z "$URL" ]; then
    MSG="🚨 **錄影沒開！**
STREAM_URL 還是空
23:25 auto-grab 4 路徑全失敗 + 大大也沒手貼
決策:
1. 大寶會在 session 醒來時手動處理
2. 或 Luma replay 24-72h 後重抓
3. 或 A 方案切 Oracle Cloud VM（如果 Luma 重抓也失敗）"

    notify_tg "$MSG"
    exit 1
fi

log "URL 已就緒 → 啟動 start.sh"
bash "$BASE_DIR/bin/start.sh" 2>&1 | tee -a "$LOG_FILE"
START_RC=$?

if [ "$START_RC" -ne 0 ]; then
    log "❌ start.sh 退出 $START_RC"
    notify_tg "🚨 start.sh 失敗（exit $START_RC）
請看 $LOG_FILE"
    exit 2
fi

# 驗證 PID
sleep 3
if [ -f "$BASE_DIR/run/recorder.pid" ] && kill -0 "$(cat "$BASE_DIR/run/recorder.pid")" 2>/dev/null; then
    PID=$(cat "$BASE_DIR/run/recorder.pid")
    log "✅ 錄影已啟動 PID=$PID"

    # 等 10 秒,跑第一次 heartbeat 驗證
    sleep 10
    bash "$BASE_DIR/bin/heartbeat.sh" 2>&1 | tee -a "$LOG_FILE"

    notify_tg "✅ **Grok Bot Galaxy 錄影已開！**
PID: $PID
URL: $URL
第一次心跳：見 logs/heartbeat.log
下次心跳：見 cron schedule"
    exit 0
else
    log "❌ PID 不存在或已死"
    notify_tg "🚨 start.sh 說成功但 PID 檢查失敗
請看 $LOG_FILE"
    exit 3
fi