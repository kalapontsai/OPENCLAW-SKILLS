#!/bin/bash
# cron wrapper for heartbeat
set -u
bash /mnt/d/record-loop/bin/heartbeat.sh > /tmp/heartbeat.out 2>&1
RC=$?
echo "EXIT=$RC"
tail -30 /mnt/d/record-loop/logs/heartbeat.log
exit 0