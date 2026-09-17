#!/bin/bash
# cron wrapper for stop + final report
set -u
echo "=== cron-stop.sh $(date) ==="
bash /mnt/d/record-loop/bin/stop.sh > /tmp/stop.out 2>&1
RC=$?
echo "STOP_RC=$RC"
echo "--- final recordings ---"
ls -lh /mnt/d/record-loop/recordings/*.ts 2>/dev/null | head -10 || echo "(no ts files)"
echo "--- total size ---"
du -sh /mnt/d/record-loop/recordings/ 2>/dev/null
echo "--- file count ---"
find /mnt/d/record-loop/recordings -name "*.ts" -type f | wc -l
echo "--- last 30 lines of record.log ---"
tail -30 /mnt/d/record-loop/logs/record.log 2>/dev/null
echo "--- last 30 lines of heartbeat.log ---"
tail -30 /mnt/d/record-loop/logs/heartbeat.log 2>/dev/null
echo "=== END cron-stop.sh ==="
exit 0