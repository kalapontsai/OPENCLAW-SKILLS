#!/bin/bash
# cron wrapper for auto-grab (called by OpenClaw automation)
set -u
bash /mnt/d/record-loop/bin/auto-grab.sh > /tmp/autograb.out 2>&1
RC=$?
echo "EXIT=$RC"
echo "--- last 30 lines of auto-grab.log ---"
tail -30 /mnt/d/record-loop/logs/auto-grab.log
echo "--- stream.env STREAM_URL ---"
grep '^STREAM_URL=' /mnt/d/record-loop/run/stream.env || echo "(empty)"
exit 0