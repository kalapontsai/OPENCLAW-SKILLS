#!/bin/bash
# notify-failure.sh - auto-grab 失敗時丟訊息給大大
# 邏輯：檢查 /tmp/galaxy-grab-failed.flag,有就訊息給 user
set -u

FLAG="/tmp/galaxy-grab-failed.flag"

if [ ! -f "$FLAG" ]; then
    echo "$(date) 沒 flag,auto-grab 應該成功了（讓 23:30 smart-start 驗證）"
    exit 0
fi

echo "$(date) flag 存在 → 通知大大"
echo "STREAM_URL=$(grep ^STREAM_URL= /mnt/d/record-loop/run/stream.env)"
echo ""
echo "⚠️ 給 agent 看的訊息:"
cat "$FLAG"