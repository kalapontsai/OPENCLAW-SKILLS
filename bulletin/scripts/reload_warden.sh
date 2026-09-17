#!/usr/bin/env bash
# reload_warden.sh — 重啟 warden (修改 scripts 後用)
set -euo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd)"
bash "$REPO/scripts/stop_warden.sh" || true
sleep 1
bash "$REPO/scripts/start_warden.sh"
