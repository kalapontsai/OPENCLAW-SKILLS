#!/usr/bin/env python3
"""
fund-plan 設定載入器

依序嘗試取得 FINMIND_TOKEN：
1. config/.env（專案本地，新約定）
2. /mnt/d/OneDrive - Sampo Corporation/3.Data/5.python/finlab_tw_screener/.env（legacy）
3. 環境變數 FINMIND_TOKEN（CI / container）

新寫的 script 一律 import 這個，不要自己讀 .env。
"""
import os
import sys
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent

# === token 來源（依優先序）===
PRIMARY_ENV = PROJECT_DIR / "config" / ".env"
LEGACY_ENV = Path("/mnt/d/OneDrive - Sampo Corporation/3.Data/5.python/finlab_tw_screener/.env")


def _load_env_file(env_path: Path) -> dict[str, str]:
    """讀 .env key=value 格式（容忍註解、空行）"""
    if not env_path.exists():
        return {}
    result = {}
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        result[k.strip()] = v.strip()
    return result


def get_finmind_token() -> str:
    """取得 FINMIND_TOKEN；找不到時拋 FileNotFoundError 帶說明"""
    for src in (PRIMARY_ENV, LEGACY_ENV):
        kv = _load_env_file(src)
        tok = kv.get("FINMIND_TOKEN", "")
        if tok and tok != "your_token_here" and len(tok) >= 10:
            return tok

    env_tok = os.environ.get("FINMIND_TOKEN", "")
    if env_tok and len(env_tok) >= 10:
        return env_tok

    raise FileNotFoundError(
        f"❌ FINMIND_TOKEN 找不到。\n"
        f"   請建立 {PRIMARY_ENV}（參考 config/.env.example）\n"
        f"   或從既有位置複製：{LEGACY_ENV}"
    )


def get_config_summary() -> dict:
    """回傳 token 來源 + 各檔存在狀態（給報告 / log 用）"""
    sources = []
    for label, path in [("config/.env", PRIMARY_ENV), ("legacy .env", LEGACY_ENV), ("ENV_VAR", None)]:
        if label == "ENV_VAR":
            if os.environ.get("FINMIND_TOKEN"):
                sources.append(label)
            continue
        kv = _load_env_file(path)
        if kv.get("FINMIND_TOKEN"):
            sources.append(f"{label} ({path})")
    return {
        "token_sources_found": sources,
        "primary_exists": PRIMARY_ENV.exists(),
        "legacy_exists": LEGACY_ENV.exists(),
    }


if __name__ == "__main__":
    # CLI 測試用：`python3 scripts/_config.py`
    try:
        tok = get_finmind_token()
        print(f"✅ Token 載入成功（長度 {len(tok)}）")
        print(f"🔍 來源：{get_config_summary()}")
    except FileNotFoundError as e:
        print(str(e))
        sys.exit(1)