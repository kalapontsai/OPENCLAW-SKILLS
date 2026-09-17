#!/bin/bash
# ============================================================
# disk-watch.sh - 磁碟監控 watchdog（WSL 版）
# 用途：磁碟使用超過閾值時自動上傳最舊檔案到 GDrive 再刪除
# 用法：cron 每 30 分鐘跑一次（或手動 ./disk-watch.sh）
# 環境變數：
#   GDRIVE_REMOTE    預設 gdrive:galaxy-recordings
#   THRESHOLD_PCT    預設 75
# 建立：2026-09-12 by 大寶
# ============================================================

set -u

DATA_DIR="/mnt/d/record-loop/recordings"
LOG_DIR_LOCAL="/mnt/d/record-loop/logs"
LOG_FILE="$LOG_DIR_LOCAL/disk-watch.log"
THRESHOLD_PCT="${THRESHOLD_PCT:-75}"
GDRIVE_REMOTE="${GDRIVE_REMOTE:-gdrive:galaxy-recordings}"
GDRIVE_BATCH_SIZE="${GDRIVE_BATCH_SIZE:-3}"

# 載入使用者設定
ENV_FILE="/mnt/d/record-loop/run/stream.env"
if [ -f "$ENV_FILE" ]; then
    # shellcheck disable=SC1090
    source "$ENV_FILE"
fi

mkdir -p "$LOG_DIR_LOCAL"

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$LOG_FILE"
}

pct() {
    df "$DATA_DIR" | tail -1 | awk '{print $5}' | tr -d '%'
}

# 確認 rclone remote 可用
if ! command -v rclone &>/dev/null; then
    log "⚠️ rclone 未安裝，跳過（裝好後自動會跑）"
    exit 0
fi

if ! rclone lsd "$GDRIVE_REMOTE" >/dev/null 2>&1; then
    log "⚠️ rclone remote '$GDRIVE_REMOTE' 不可用，跳過（執行 rclone config 設定）"
    exit 0
fi

CURRENT_PCT=$(pct)
log "目前磁碟使用：${CURRENT_PCT}%"

if [ "$CURRENT_PCT" -lt "$THRESHOLD_PCT" ]; then
    log "低於閾值（${THRESHOLD_PCT}%），沒事"
    exit 0
fi

log "⚠️ 超過閾值，開始上傳最舊的 $GDRIVE_BATCH_SIZE 個檔案..."

mapfile -t OLD_FILES < <(find "$DATA_DIR" -name "*.ts" -type f -printf '%T@ %p\n' \
    | sort -n | head -n "$GDRIVE_BATCH_SIZE" | awk '{print $2}')

if [ ${#OLD_FILES[@]} -eq 0 ]; then
    log "找不到 .ts 檔案"
    exit 0
fi

for FILE in "${OLD_FILES[@]}"; do
    BASENAME=$(basename "$FILE")
    log "上傳 $BASENAME → $GDRIVE_REMOTE"
    if rclone copyto "$FILE" "$GDRIVE_REMOTE/$BASENAME" 2>> "$LOG_FILE"; then
        SIZE=$(stat -c%s "$FILE")
        rm -f "$FILE"
        log "✅ 已上傳並刪除 $BASENAME ($((SIZE/1024/1024)) MB)"
    else
        log "❌ 上傳失敗，保留本地檔案"
    fi
done

log "處理後磁碟使用：$(pct)%"