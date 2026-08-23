#!/usr/bin/env bash
# check_warden.sh — 監看 warden 是否活著 + v1.8.0 派工 trigger 給 consumer agent
#
# 設計：
#   - 若 PIDFILE 存在但 PID 已死 → 視為「非預期死亡」，自動重啟 + 寫 log
#   - 若 PIDFILE 不存在 → 視為「使用者刻意不啟動」，不動作（避免誤啟）
#   - 若 PIDFILE 存在且 PID 活著 → 沒事，跳出
#
# v1.8.0 新增（2026-08-23）：dispatch cowork triggers（§6.6+）
#   - 掃 ~/.openclaw/agent-cowork/.trigger-<agent> 檔
#   - 對每個 trigger → openclaw message send --account bot-<agent> 推醒對應 agent
#   - wake 成功 → 刪 trigger；失敗 → 留著下次 retry
#
# 用法：被 cron 或其他 scheduler 定期呼叫（建議 2 分鐘）
#   bash scripts/check_warden.sh
#
# 觸發時機：warden 寫的 .writeback-*.json 沒人撿 → Q&A 沒寫入
# 教訓（2026-08-21）：warden PID 55813 之後沒人監看，導致 payload 卡 12 分鐘
set -euo pipefail

PIDFILE="$HOME/.openclaw/agent-cowork/warden.pid"
LOGFILE="$HOME/.openclaw/agent-cowork/warden.log"
REPO="$HOME/.openclaw/workspace-two/repos/agents-bulletin"
TRIGGER_DIR="$HOME/.openclaw/agent-cowork"
USER_TARGET="telegram:8774080801"
TS() { date +%Y-%m-%dT%H:%M:%S%z; }

# ───────────────────── v1.8.0: dispatch triggers（先做，這是主軸）─────────────────────
# 即使 warden 死了也要 dispatch trigger，避免 agent 永遠收不到 cowork 變動
shopt -s nullglob
for trigger in "$TRIGGER_DIR"/.trigger-*; do
    [ -f "$trigger" ] || continue
    fname="$(basename "$trigger")"
    agent="${fname#.trigger-}"

    # 讀 trigger 內容組訊息
    thread_ids="$(python3 -c "
import json,sys
try:
    d = json.load(open(sys.argv[1], encoding='utf-8'))
    ids = d.get('thread_ids', [])
    print(', '.join(ids) if ids else '(none)')
except Exception as e:
    print(f'(parse err: {e})')
" "$trigger" 2>/dev/null || echo '(read err)')"

    msg="🔔 cowork trigger [$agent]: $thread_ids（check §6.1 Responder SOP）"

    echo "[$(TS)] 🔔 dispatch: $fname → bot-$agent (tids: $thread_ids)" >> "$LOGFILE"

    # wake agent via message send（指定 account → 只觸發該 bot 的 inbound）
    if openclaw message send \
            --channel telegram \
            --account "bot-$agent" \
            --target "$USER_TARGET" \
            --message "$msg" >> "$LOGFILE" 2>&1; then
        echo "[$(TS)] ✅ wake bot-$agent sent, removing $fname" >> "$LOGFILE"
        rm -f "$trigger"
    else
        rc=$?
        echo "[$(TS)] ❌ wake bot-$agent failed (rc=$rc), keep $fname for retry" >> "$LOGFILE"
    fi
done
shopt -u nullglob

# ───────────────────── 原職責：監看 warden ─────────────────────
# 沒 PIDFILE → 不啟動（可能是使用者刻意關掉）
if [ ! -f "$PIDFILE" ]; then
  exit 0
fi

PID="$(cat "$PIDFILE")"

# PID 活著 → 沒事（trigger 已在上面處理完）
if kill -0 "$PID" 2>/dev/null; then
  exit 0
fi

# 到這裡 = PIDFILE 存在但 PID 死了
echo "[$(TS)] ⚠️  warden dead (pid=$PID, pidfile stale). Auto-restarting..." >> "$LOGFILE"
rm -f "$PIDFILE"

cd "$REPO"
setsid nohup python3 scripts/warden.py > /dev/null 2>&1 < /dev/null &
WPID=$!
echo "$WPID" > "$PIDFILE"
disown || true
sleep 1

if kill -0 "$WPID" 2>/dev/null; then
  echo "[$(TS)] ✅ warden auto-restarted, pid=$WPID" >> "$LOGFILE"
else
  echo "[$(TS)] ❌ warden auto-restart FAILED, pid=$WPID" >> "$LOGFILE"
  exit 1
fi