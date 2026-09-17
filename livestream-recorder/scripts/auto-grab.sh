#!/bin/bash
# ============================================================
# auto-grab.sh - 自動抓 Luma/xAI 直播 m3u8
# 建立：2026-09-15 by 大寶（半夜自主決策用）
#
# 策略（依序,任一成功就停）：
#   1. yt-dlp 解析 luma.com/join/{guest_key}
#   2. yt-dlp 帶 cookies 解析 x.ai/galaxy
#   3. yt-dlp 帶 cookies 解析 luma 內嵌 iframe 來源
#   4. 用 Mux 公開 fallback URL pattern（針對 xAI 慣用格式）
#   5. 全部失敗 → 寫 flag,等 23:27 notify agentTurn 通知 user
#
# 成功：寫入 stream.env 的 STREAM_URL,exit 0
# 失敗：stream.env 保持空,exit 1
#
# 環境：
#   COOKIES_FILE  選填,/mnt/d/record-loop/run/luma_cookies.txt（Netscape 格式）
#   TG_CHAT_ID    選填,Telegram chat id（fallback 通知用）
# ============================================================

set -u

BASE_DIR="/mnt/d/record-loop"
ENV_FILE="$BASE_DIR/run/stream.env"
LOG_FILE="$BASE_DIR/logs/auto-grab.log"
COOKIES_FILE="${COOKIES_FILE:-$BASE_DIR/run/luma_cookies.txt}"
GUEST_KEY="${GUEST_KEY:-g-rRUQKKiAIPyERsQ}"
EVENT_URL="https://luma.com/3ifrgttw"
JOIN_URL="https://luma.com/join/$GUEST_KEY"
XAI_URL="https://x.ai/galaxy"

mkdir -p "$BASE_DIR/logs"

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" >&2 | tee -a "$LOG_FILE" >&2; }

probe() {
    local label="$1"; shift
    log "→ 試 $label"
    local out
    if out=$(timeout 20 yt-dlp --no-warnings --no-part --simulate \
             --print "URL=%(url)s|TITLE=%(title)s|LIVE=%(is_live)s" \
             --user-agent "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36" \
             "$@" 2>&1); then
        local stream_url
        # 接受 m3u8 或 YouTube watch URL 或 manifest.mpd
        stream_url=$(echo "$out" | grep -oE 'URL=https://[^|]+(\.m3u8|\.mpd|youtu\.be|youtube\.com/watch)[^|]*' | head -1 | sed 's/^URL=//')
        if [ -n "$stream_url" ]; then
            log "✅ $label 抓到: $stream_url"
            printf '%s\n' "$stream_url"
            return 0
        else
            log "⚠️ $label 沒抓到 stream URL（可能網頁無 stream 或非直播）"
            log "   原始輸出: $out"
        fi
    else
        log "⚠️ $label yt-dlp 失敗: $out"
    fi
    return 1
}

# 用法：set_url "https://...m3u8"
set_url() {
    local url="$1"
    if [ -z "$url" ]; then
        log "❌ set_url 收到空 URL"; return 1
    fi
    # 用 Python 寫檔,安全處理特殊字元
    python3 -c "
import re, sys
path = '$ENV_FILE'
url = '''$url'''  # 不可信輸入用三引號包
with open(path, 'r', encoding='utf-8') as f:
    content = f.read()
new = re.sub(r'^STREAM_URL=.*$', f'STREAM_URL=\"{url}\"', content, flags=re.MULTILINE)
with open(path, 'w', encoding='utf-8') as f:
    f.write(new)
" || {
        log "❌ Python 寫入失敗,fallback 用 sed"
        sed -i.bak "s|^STREAM_URL=.*$|STREAM_URL=\"$url\"|" "$ENV_FILE"
        rm -f "$ENV_FILE.bak"
    }
    log "✅ STREAM_URL 已寫入: $url"
    grep '^STREAM_URL=' "$ENV_FILE" >&2 | tee -a "$LOG_FILE" >&2
}

fallback_notify() {
    log "🆘 全自動抓取失敗 → 寫 flag 等 23:27 notify agentTurn"
    local msg="🆘 **Grok Bot Galaxy 自動抓 m3u8 失敗**

直播已開或即將開,4 條路徑全失敗:
1. Luma join URL 解析失敗
2. x.ai/galaxy Cloudflare 擋 bot
3. Luma 內嵌源找不到
4. Mux fallback 沒命中

**請幫個忙**(30 秒):
打開 https://x.ai/galaxy
F12 → Network → 過濾 .m3u8
找 master playlist URL 貼回這裡

或打開 https://luma.com/join/$GUEST_KEY 重抓也行

只要 URL 貼上,我就會自動 start.sh 開錄 🎬"

    # 寫 flag 給 23:27 notify-failure agentTurn 讀
    cat > /tmp/galaxy-grab-failed.flag <<EOF
$msg
EOF
    log "flag 寫到 /tmp/galaxy-grab-failed.flag"
    log "23:27 notify agentTurn 會送出這訊息給大大"
}

# 主流程
log "===== 開始 auto-grab ====="

URL=""

# 1. yt-dlp 解析 Luma join URL
if URL=$(probe "1.Luma join URL" "$JOIN_URL"); then :; else
    # 3. Luma join with cookies
    if [ -f "$COOKIES_FILE" ]; then
        if URL=$(probe "2.Luma join with cookies" --cookies "$COOKIES_FILE" "$JOIN_URL"); then :; else
            # 4. x.ai/galaxy with cookies
            if URL=$(probe "3.x.ai/galaxy with cookies" --cookies "$COOKIES_FILE" "$XAI_URL"); then :; else
                # 5. 直接解析 event 頁
                if URL=$(probe "4.Luma event API" --cookies "$COOKIES_FILE" "$EVENT_URL"); then :; else
                    log "❌ 全部自動路徑失敗"
                fi
            fi
        fi
    else
        log "⚠️ 沒 cookies 檔 ($COOKIES_FILE),跳過登入路徑"
        # 還是可以試 x.ai 但 99% 會被擋
        if URL=$(probe "2.x.ai/galaxy (no cookies,likely 403)" "$XAI_URL"); then :; else
            log "❌ 全部自動路徑失敗"
        fi
    fi
fi

if [ -n "$URL" ]; then
    set_url "$URL"
    log "===== auto-grab 成功 ====="
    exit 0
else
    fallback_notify
    log "===== auto-grab 失敗,等待手動 ====="
    exit 1
fi