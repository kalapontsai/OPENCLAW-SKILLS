#!/bin/bash
# ~/.openclaw/agent-cowork/health-check.sh
# Agent Cowork Protocol 監控腳本
# 排除協議文件，檢查主目錄/archive/routing/HEARTBEAT
#
# Exit code:
#   0 = 健康
#   1 = 警告（觀察中）
#   2 = 異常（需通知主人）
#
# 跑法：
#   ~/.openclaw/agent-cowork/health-check.sh

set -e
COWORK="$HOME/.openclaw/agent-cowork"
EXCLUDE_REGEX='SKILL\.md|README\.md|\.template\.md|HEARTBEAT-snippet\.md|\.bak|proposal\.md'

WARNINGS=0
ERRORS=0
ISSUES=""

# 1. 主目錄未讀檔案數量
INBOX=$(ls "$COWORK"/*.md 2>/dev/null | grep -vE "$EXCLUDE_REGEX" | wc -l)
if [ "$INBOX" -le 5 ]; then
    echo "✅ 主目錄未讀：$INBOX 個（健康）"
elif [ "$INBOX" -le 10 ]; then
    echo "⚠️  主目錄未讀：$INBOX 個（累積但不嚴重）"
    WARNINGS=$((WARNINGS + 1))
    ISSUES="$ISSUES\n⚠️ 主目錄有 $INBOX 個未讀（>5 較多）"
else
    echo "🛑 主目錄未讀：$INBOX 個（堆積嚴重）"
    ERRORS=$((ERRORS + 1))
    ISSUES="$ISSUES\n🛑 主目錄有 $INBOX 個未讀（堆積）"
fi

# 2. 排除協議文件，掃主目錄訊息
INBOX_FILES=$(ls "$COWORK"/*.md 2>/dev/null | grep -vE "$EXCLUDE_REGEX" || true)

# 3. critical 訊息卡 > 24h
if [ -n "$INBOX_FILES" ]; then
    STUCK_CRITICAL=0
    while IFS= read -r f; do
        [ -z "$f" ] && continue
        if [ -f "$f" ] && grep -q '^priority: critical' "$f" 2>/dev/null; then
            # mtime > 1 day (= 86400 sec)
            if [ "$(find "$f" -mtime +1 2>/dev/null | wc -l)" -gt 0 ]; then
                STUCK_CRITICAL=$((STUCK_CRITICAL + 1))
                ISSUES="$ISSUES\n🛑 critical 卡 >24h：$(basename "$f")"
            fi
        fi
    done <<< "$INBOX_FILES"
    if [ "$STUCK_CRITICAL" -eq 0 ]; then
        echo "✅ 無 stuck critical（>24h）"
    else
        echo "🛑 有 $STUCK_CRITICAL 個 critical 訊息卡 >24h"
        ERRORS=$((ERRORS + 1))
    fi
fi

# 4. 4 個 agent HEARTBEAT.md 套 v1.2 SOP
for d in workspace workspace-stock workspace-two workspace-three; do
    if [ -f "$HOME/.openclaw/$d/HEARTBEAT.md" ] && grep -q 'v1\.2' "$HOME/.openclaw/$d/HEARTBEAT.md" 2>/dev/null; then
        echo "✅ $d: 已套 v1.2 SOP"
    else
        echo "🛑 $d: 沒套 v1.2 SOP"
        ERRORS=$((ERRORS + 1))
        ISSUES="$ISSUES\n🛑 $d HEARTBEAT.md 沒套 v1.2"
    fi
done

# 5. 檔名 routing 檢查（識別舊格式）
#    v1.1 格式：<sender>-to-<receiver>-...
#    v1.2 格式：<initiator>-thread-...-for-<receiver>-...
if [ -n "$INBOX_FILES" ]; then
    OLD_FORMAT=0
    while IFS= read -r f; do
        [ -z "$f" ] && continue
        base=$(basename "$f")
        # 向後相容：v1.1 (^-to-) 或 v1.2 (-thread-...-for-) 都算合規
        if ! echo "$base" | grep -qE '^[^-]+-(to-[a-z]+|thread-.*-for-[a-z]+)'; then
            OLD_FORMAT=$((OLD_FORMAT + 1))
        fi
    done <<< "$INBOX_FILES"
    if [ "$OLD_FORMAT" -eq 0 ]; then
        echo "✅ 主目錄檔名 routing 合規（v1.1 / v1.2 都接受）"
    else
        echo "⚠️  主目錄有 $OLD_FORMAT 個舊格式檔名（v1.0 過渡期）"
        WARNINGS=$((WARNINGS + 1))
        ISSUES="$ISSUES\n⚠️ 有 $OLD_FORMAT 個舊格式檔名（v1.0 過渡期）"
    fi
fi

# 6. archive 內 status 分布（排除 README 規則文件）
if [ -d "$COWORK/archive" ]; then
    ARCHIVE_FILES=$(find "$COWORK/archive" -name '*.md' ! -name 'README.md' 2>/dev/null | wc -l)
    if [ "$ARCHIVE_FILES" -gt 0 ]; then
        NOT_DONE=$(find "$COWORK/archive" -name '*.md' ! -name 'README.md' 2>/dev/null | while read f; do
            if ! grep -q '^status: done' "$f" 2>/dev/null; then
                echo "$f"
            fi
        done | wc -l)
        if [ "$NOT_DONE" -eq 0 ]; then
            echo "✅ archive 內全部 done（$ARCHIVE_FILES 個）"
        else
            echo "⚠️  archive 有 $NOT_DONE / $ARCHIVE_FILES 個 done 以外的狀態"
            WARNINGS=$((WARNINGS + 1))
            ISSUES="$ISSUES\n⚠️ archive 有 $NOT_DONE 個未 done 的訊息"
        fi
    else
        echo "ℹ️  archive 為空（訊息還沒開始歸檔）"
    fi
else
    echo "ℹ️  archive/ 目錄不存在"
fi

# 總結
echo ""
echo "===== 總結 ====="
if [ "$ERRORS" -gt 0 ]; then
    echo "🛑 狀態：異常（$ERRORS 個錯誤 / $WARNINGS 個警告）"
    echo "--- 異常項目 ---"
    echo -e "$ISSUES"
    exit 2
elif [ "$WARNINGS" -gt 0 ]; then
    echo "⚠️  狀態：警告（$WARNINGS 個警告）"
    echo "--- 警告項目 ---"
    echo -e "$ISSUES"
    exit 1
else
    echo "✅ 狀態：健康"
    exit 0
fi
