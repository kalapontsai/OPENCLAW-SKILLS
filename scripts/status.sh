#!/bin/bash
# ============================================================
# status.sh - 檢查錄影狀態
# 用法：./status.sh
# ============================================================

set -u

BASE_DIR="/mnt/d/record-loop"
PID_FILE="$BASE_DIR/run/recorder.pid"
DATA_DIR="$BASE_DIR/recordings"
LOG_DIR_LOCAL="$BASE_DIR/logs"

echo "=========================================="
echo " Grok Bot Galaxy 錄影狀態"
echo "=========================================="

# 1. 進程狀態
if [ -f "$PID_FILE" ]; then
    PID=$(cat "$PID_FILE")
    if kill -0 "$PID" 2>/dev/null; then
        echo "✅ 錄影運行中 (PID $PID)"
        UPTIME=$(ps -o etime= -p "$PID" 2>/dev/null | xargs)
        echo "   已運行：$UPTIME"
    else
        echo "❌ PID 檔存在但進程已死 (stale PID $PID)"
    fi
else
    echo "⏸️  未運行"
fi

# 2. 磁碟
echo ""
echo "📀 磁碟使用："
df -h "$DATA_DIR" | tail -1 | awk '{print "   "$1" "$2" / "$3" ("$5" used)"}'

# 3. 錄影檔案統計
echo ""
echo "🎬 錄影檔案："
TS_COUNT=$(find "$DATA_DIR" -name "*.ts" -type f 2>/dev/null | wc -l)
TS_SIZE=$(du -sh "$DATA_DIR" 2>/dev/null | awk '{print $1}')
echo "   $TS_COUNT 個 .ts 檔，總大小 $TS_SIZE"

if [ "$TS_COUNT" -gt 0 ]; then
    echo "   最新 5 個："
    find "$DATA_DIR" -name "*.ts" -type f -printf '%T@ %s %p\n' \
        | sort -rn | head -5 \
        | awk '{
            cmd="date -d @"$1" \"+%Y-%m-%d %H:%M:%S\""
            cmd | getline t
            close(cmd)
            printf "     %s  %8.1f MB  %s\n", t, $2/1024/1024, $3
        }'
fi

# 4. 最近日誌
echo ""
echo "📋 最近 5 行 record.log："
if [ -f "$LOG_DIR_LOCAL/record.log" ]; then
    tail -5 "$LOG_DIR_LOCAL/record.log" | sed 's/^/   /'
else
    echo "   （無）"
fi

echo ""
echo "=========================================="