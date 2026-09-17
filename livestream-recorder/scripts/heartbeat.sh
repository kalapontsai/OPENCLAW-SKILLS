#!/bin/bash
# ============================================================
# heartbeat.sh - 錄影狀態心跳檢查
# 建立：2026-09-15 by 大寶
#
# 用法：被 cron 排程每 30 分鐘跑一次（23:30 之後）
# 功能：
#   1. 檢查 recorder.pid 還在不在
#   2. 檢查 .ts 檔有在長大
#   3. 檢查 record.log 沒卡死（最後一行時間 < 5 分鐘前）
#   4. 異常 → 寫 log + 發 Telegram 給大大
# 輸出：append 到 /mnt/d/record-loop/logs/heartbeat.log
# ============================================================

set -u

BASE_DIR="/mnt/d/record-loop"
PID_FILE="$BASE_DIR/run/recorder.pid"
LOG_FILE="$BASE_DIR/logs/heartbeat.log"
RECORDINGS="$BASE_DIR/recordings"
RECORD_LOG="$BASE_DIR/logs/record.log"

mkdir -p "$(dirname "$LOG_FILE")"

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$LOG_FILE"; }

STATUS="OK"
DETAILS=""

# 1. PID 在不在
if [ -f "$PID_FILE" ]; then
    PID=$(cat "$PID_FILE")
    if kill -0 "$PID" 2>/dev/null; then
        UPTIME=$(ps -o etime= -p "$PID" 2>/dev/null | xargs)
        DETAILS="$DETAILS|PID=$PID alive($UPTIME)"
    else
        STATUS="FAIL"
        DETAILS="$DETAILS|PID=$PID DEAD"
    fi
else
    STATUS="FAIL"
    DETAILS="$DETAILS|NO PID FILE"
fi

# 2. 最新 .ts 檔大小
LATEST_TS=$(find "$RECORDINGS" -name "*.ts" -type f -printf '%T@ %s %p\n' 2>/dev/null \
    | sort -rn | head -1)
if [ -n "$LATEST_TS" ]; then
    TS_TIME=$(echo "$LATEST_TS" | awk '{print $1}')
    TS_SIZE=$(echo "$LATEST_TS" | awk '{print $2}')
    TS_PATH=$(echo "$LATEST_TS" | awk '{print $3}')
    TS_AGE=$(($(date +%s) - ${TS_TIME%.*}))
    SIZE_MB=$((TS_SIZE / 1024 / 1024))
    DETAILS="$DETAILS|last_ts=$(basename "$TS_PATH") ${SIZE_MB}MB ${TS_AGE}s_ago"
    if [ "$TS_AGE" -gt 600 ] && [ "$SIZE_MB" -gt 1 ]; then
        STATUS="WARN"
        DETAILS="$DETAILS|TIMESTAMP STALE (>10min)"
    fi
else
    if [ "$STATUS" = "OK" ]; then
        STATUS="WARN"
    fi
    DETAILS="$DETAILS|NO TS FILE YET"
fi

# 3. record.log 最後活動時間
if [ -f "$RECORD_LOG" ]; then
    LAST_LOG_TIME=$(stat -c %Y "$RECORD_LOG" 2>/dev/null)
    LAST_LOG_AGE=$(($(date +%s) - LAST_LOG_TIME))
    DETAILS="$DETAILS|log_age=${LAST_LOG_AGE}s"
    if [ "$LAST_LOG_AGE" -gt 600 ]; then
        STATUS="WARN"
        DETAILS="$DETAILS|LOG STALE (>10min)"
    fi
else
    DETAILS="$DETAILS|no record.log"
fi

# 4. 磁碟
DISK_PCT=$(df "$RECORDINGS" | tail -1 | awk '{print $5}' | tr -d '%')
DETAILS="$DETAILS|disk=${DISK_PCT}%"

log "$STATUS$DETAILS"

# 失敗才發 Telegram（避免刷頻）
if [ "$STATUS" = "FAIL" ]; then
    MSG="🚨 **錄影心跳失敗** $DETAILS
請查 status.sh / record.log"
    if [ -n "${TG_CHAT_ID:-}" ] && [ -n "${TELEGRAM_BOT_TOKEN:-}" ]; then
        curl -s -X POST "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage" \
            -d "chat_id=$TG_CHAT_ID" -d "text=$MSG" \
            -d "parse_mode=Markdown" >> "$LOG_FILE" 2>&1
    fi
fi