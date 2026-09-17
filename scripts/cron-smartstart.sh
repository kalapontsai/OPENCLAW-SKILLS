#!/bin/bash
# cron wrapper for smart-start
set -u
bash /mnt/d/record-loop/bin/smart-start.sh > /tmp/smartstart.out 2>&1
RC=$?
echo "EXIT=$RC"
echo "--- last 30 lines of smart-start.log ---"
tail -30 /mnt/d/record-loop/logs/smart-start.log
echo "--- recorder.pid ---"
cat /mnt/d/record-loop/run/recorder.pid 2>/dev/null || echo "(none)"
exit 0