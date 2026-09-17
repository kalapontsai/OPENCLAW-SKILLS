#!/usr/bin/env python3
"""
fund-plan constraints 載入器（v1.4）

讀取 portfolio/constraints.json：
- whitelist：強制保留的 ticker + 權重上下限
- blacklist：絕對排除的 ticker
- combo_size：min/max/prefer

設計：
- 找不到檔案 → 回傳 None（視同無約束）
- schema 錯誤 → raise ValueError + 印說明
- agent 應該在 phase 1/3/6 開頭呼叫 load_constraints()
"""
import json
import sys
from pathlib import Path
from typing import Optional

PROJECT_DIR = Path(__file__).resolve().parent.parent
CONSTRAINTS_PATH = PROJECT_DIR / "portfolio" / "constraints.json"


def load_constraints(path: Optional[Path] = None) -> Optional[dict]:
    """讀 constraints.json；找不到回傳 None"""
    p = path or CONSTRAINTS_PATH
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise ValueError(f"❌ constraints.json 不是合法 JSON：{e}\n   檔案：{p}")


def get_whitelist_tickers(c: Optional[dict]) -> list:
    """回傳白名單 ticker 列表"""
    if not c:
        return []
    return [w["ticker"] for w in c.get("whitelist", [])]


def get_blacklist_tickers(c: Optional[dict]) -> list:
    """回傳黑名單 ticker 列表"""
    if not c:
        return []
    return [b["ticker"] for b in c.get("blacklist", [])]


def get_combo_size(c: Optional[dict]) -> dict:
    """回傳組合大小設定 {min, max, prefer}；無 constraints 用預設"""
    if not c or "combo_size" not in c:
        return {"min": 3, "max": 7, "prefer": 5, "note": "default"}
    cs = c["combo_size"]
    return {
        "min": cs.get("min", 3),
        "max": cs.get("max", 7),
        "prefer": cs.get("prefer", 5),
        "note": cs.get("note", ""),
    }


def validate_constraints(c: dict) -> list:
    """回傳警告列表（不 raise，僅 log）；主人決策用"""
    warnings = []
    if not c:
        return warnings

    wl = c.get("whitelist", [])
    bl = c.get("blacklist", [])
    cs = c.get("combo_size", {})

    # whitelist > max
    if len(wl) > cs.get("max", 7):
        warnings.append(
            f"⚠️ whitelist 有 {len(wl)} 個、> combo_size.max={cs.get('max')} → "
            f"需主人決定是否擴大 max"
        )

    # blacklist 包含 5 核心（00690/00878/00881/00918/00935）
    core5 = {"00690", "00878", "00881", "00918", "00935"}
    conflict = [b["ticker"] for b in bl if b["ticker"] in core5]
    if conflict:
        warnings.append(
            f"🔴 blacklist 含 5 核心 {conflict} → 需主人確認"
        )

    # combo_size.prefer < len(whitelist)
    prefer = cs.get("prefer", 5)
    if len(wl) > prefer:
        warnings.append(
            f"ℹ️ whitelist {len(wl)} > prefer {prefer} → 自動擴大 prefer = {len(wl)}"
        )

    return warnings


def filter_universe_by_constraints(universe_tickers: list, c: Optional[dict]) -> tuple:
    """
    套用 constraints 過濾 universe：
    - blacklist 全排除
    - whitelist 若不在 universe → log warning（可能已下市）

    回傳：(filtered_tickers, warnings)
    """
    if not c:
        return universe_tickers, []

    bl = set(get_blacklist_tickers(c))
    wl = set(get_whitelist_tickers(c))

    # 排除 blacklist
    filtered = [t for t in universe_tickers if t not in bl]

    # 檢查 whitelist
    warnings = []
    missing_wl = [t for t in wl if t not in universe_tickers]
    if missing_wl:
        warnings.append(f"⚠️ whitelist 在 universe 找不到：{missing_wl}（可能已下市）")

    return filtered, warnings


if __name__ == "__main__":
    # CLI 測試
    c = load_constraints()
    if not c:
        print("❌ portfolio/constraints.json 不存在（視同無約束）")
        sys.exit(1)

    print(f"✅ 載入 constraints.json（version={c.get('version', '?')}）")
    print(f"   白名單：{get_whitelist_tickers(c)}")
    print(f"   黑名單：{get_blacklist_tickers(c)}")
    cs = get_combo_size(c)
    print(f"   combo_size：min={cs['min']} max={cs['max']} prefer={cs['prefer']}")
    warnings = validate_constraints(c)
    if warnings:
        print("\n⚠️ 警告：")
        for w in warnings:
            print(f"   {w}")