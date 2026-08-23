#!/usr/bin/env bash
# deploy.sh — 同步 deploy/ 內 HTML/PHP/CSS/JS 到 web root
#
# 用法：bash scripts/deploy.sh
# 設計：冪等、可重複跑、rsync 風格（這版用 cp + clean）
set -euo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
DEPLOY="$REPO/deploy"
WEB_ROOT="/mnt/d/docker-volumn/ubuntu-apache2/html/agent-bulletin"

if [ ! -d "$WEB_ROOT" ]; then
  echo "❌ web root 不存在: $WEB_ROOT"
  exit 1
fi

cd "$DEPLOY"

# 複製 .html .css .js .php（非 data/）
# 用 cp -ru (update only) + 確保子目錄
copy_files() {
  local src="$1" dst="$2"
  if [ -d "$src" ]; then
    mkdir -p "$dst"
    # rsync 不可用時改 find + cp
    if command -v rsync >/dev/null 2>&1; then
      rsync -a --delete "$src/" "$dst/"
    else
      find "$src" -mindepth 1 -maxdepth 1 -exec cp -r {} "$dst/" \;
    fi
  fi
}

copy_files "$DEPLOY/api"    "$WEB_ROOT/api"
copy_files "$DEPLOY/assets" "$WEB_ROOT/assets"

for f in *.html; do
  [ -f "$f" ] || continue
  cp "$f" "$WEB_ROOT/$f"
done

echo "✅ deploy done → $WEB_ROOT"
ls -la "$WEB_ROOT" | head -20
