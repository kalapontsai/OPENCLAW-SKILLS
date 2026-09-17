#!/bin/bash
# ============================================================
# record-loop.sh - 自動重啟 + 分段錄影（WSL 版）
# 用法：被 start.sh 呼叫，或直接 STREAM_URL=... ./record-loop.sh
# 環境變數：
#   STREAM_URL       必填，直播 .m3u8 URL
#   SEGMENT_SECONDS  選填，預設 3600（每小時切一片）
#   OUTPUT_DIR       選填，預設 /mnt/d/record-loop/recordings
#   MAX_DISK_PCT     選填，預設 85（超過砍最舊）
# 建立：2026-09-12 by 大寶
# ============================================================

set -u

# 載入 stream.env（如果存在）
ENV_FILE="/mnt/d/record-loop/run/stream.env"
if [ -f "$ENV_FILE" ]; then
    # shellcheck disable=SC1090
    source "$ENV_FILE"
fi

STREAM_URL="${STREAM_URL:?STREAM_URL 未設定，請編輯 $ENV_FILE}"
SEGMENT_SECONDS="${SEGMENT_SECONDS:-3600}"
OUTPUT_DIR="${OUTPUT_DIR:-/mnt/d/record-loop/recordings}"
MAX_DISK_PCT="${MAX_DISK_PCT:-85}"
LOG_DIR_LOCAL="/mnt/d/record-loop/logs"
PID_FILE="/mnt/d/record-loop/run/recorder.pid"

mkdir -p "$OUTPUT_DIR" "$LOG_DIR_LOCAL" "$(dirname "$PID_FILE")"

# 把自己的 PID 寫下來（給 status / stop 用）
echo $$ > "$PID_FILE"

cleanup_old_files() {
    local pct
    pct=$(df "$OUTPUT_DIR" | tail -1 | awk '{print $5}' | tr -d '%')
    if [ "$pct" -ge "$MAX_DISK_PCT" ]; then
        echo "[$(date)] 磁碟 ${pct}%，砍最舊 3 個 .ts..."
        find "$OUTPUT_DIR" -name "*.ts" -type f -printf '%T@ %p\n' \
            | sort -n | head -3 | awk '{print $2}' | xargs -r rm -f
    fi
}

trap 'echo "[$(date)] 收到終止訊號"; rm -f "$PID_FILE"; exit 0' SIGTERM SIGINT

ATTEMPT=0
while true; do
    ATTEMPT=$((ATTEMPT + 1))
    TIMESTAMP=$(date +%Y%m%d_%H%M%S)
    OUTPUT="$OUTPUT_DIR/galaxy_${TIMESTAMP}_a${ATTEMPT}.ts"

    {
        echo "[$(date)] ===== 第 $ATTEMPT 次錄影 ====="
        echo "[$(date)] URL: $STREAM_URL"
        echo "[$(date)] 輸出: $OUTPUT"
    } | tee -a "$LOG_DIR_LOCAL/record.log"

    yt-dlp \
        --no-part \
        --no-warnings \
        -o "$OUTPUT" \
        "$STREAM_URL" \
        >> "$LOG_DIR_LOCAL/record.log" 2>&1

    EXIT_CODE=$?
    SIZE=$(stat -c%s "$OUTPUT" 2>/dev/null || echo 0)
    SIZE_MB=$((SIZE / 1024 / 1024))
    {
        echo "[$(date)] yt-dlp 退出 code=$EXIT_CODE, 檔案 ${SIZE_MB} MB"
    } | tee -a "$LOG_DIR_LOCAL/record.log"

    # 太小的檔案當失敗處理
    if [ "$SIZE" -lt 1048576 ]; then
        echo "[$(date)] 檔案 < 1MB，視為失敗刪除" | tee -a "$LOG_DIR_LOCAL/record.log"
        rm -f "$OUTPUT"
    fi

    cleanup_old_files

    echo "[$(date)] 5 秒後重試..." | tee -a "$LOG_DIR_LOCAL/record.log"
    sleep 5
done