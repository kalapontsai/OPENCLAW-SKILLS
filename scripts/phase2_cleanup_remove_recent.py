#!/usr/bin/env python3
"""
fund-plan Phase 2 cleanup: 移除上市未滿 1 年的 ETF

主人 #5058 指示：清單未完成的股票，若上市未滿 1 年的直接移除。
對 single_metrics_blank.csv 的 89 檔用 yfinance firstTradeDate 找出
listed_date >= 2025-08-29 的，從 universe + blank + all 移除。
"""
import sys, json, time
from pathlib import Path
from datetime import datetime

import pandas as pd
import yfinance as yf

PROJECT_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_DIR / "data"
OUT_DIR = PROJECT_DIR / "outputs"
LOG_DIR = PROJECT_DIR / "logs"

CUTOFF = pd.Timestamp("2025-08-29")  # 主人要：上市未滿 1 年（今天 2026-08-29）


def log(msg):
    ts = time.strftime("%H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line, flush=True)
    (LOG_DIR / "phase2_cleanup.log").open("a", encoding="utf-8").write(line + "\n")


def get_first_trade_date(tid: str, max_retry: int = 2):
    """從 yfinance 抓 firstTradeDate (Unix timestamp)，轉成 pd.Timestamp"""
    for attempt in range(1, max_retry + 1):
        try:
            t = yf.Ticker(f"{tid}.TW")
            info = t.info
            ftd = info.get("firstTradeDate") or info.get("firstTradeDateMilliseconds")
            if ftd:
                # yfinance 有時回傳 ms 有時回傳 seconds
                if ftd > 10**12:
                    ftd = ftd / 1000.0
                return pd.Timestamp.fromtimestamp(ftd)
            return None
        except Exception as e:
            log(f"  �️ {tid} attempt {attempt}: {type(e).__name__}")
            time.sleep(1.0)
    return None


def main():
    log("=" * 60)
    log("🧹 Phase 2 cleanup: 移除上市未滿 1 年 (cutoff 2025-08-29)")
    log("=" * 60)

    # 讀 blank
    blank = pd.read_csv(OUT_DIR / "single_metrics_blank.csv")
    log(f"� Blank 數: {len(blank)}")

    universe = pd.read_csv(DATA_DIR / "etf_universe_raw.csv")
    log(f"📊 Universe 數: {len(universe)}")

    # 抓 firstTradeDate
    listed = {}
    for i, tid in enumerate(blank["tid"]):
        if i % 10 == 0:
            log(f"� {i+1}/{len(blank)} — {tid}")
        ld = get_first_trade_date(tid)
        listed[tid] = ld
        time.sleep(0.3)  # polite delay

    # 分類
    remove_tids = []
    keep_tids = []
    unknown_tids = []
    for tid in blank["tid"]:
        ld = listed.get(tid)
        if ld is None:
            unknown_tids.append(tid)
            keep_tids.append(tid)  # 找不到的預設保留（不誤刪）
        elif ld >= CUTOFF:
            remove_tids.append(tid)
        else:
            keep_tids.append(tid)

    log(f"🗑️  移除 (listed >= 2025-08-29): {len(remove_tids)} 檔")
    log(f"❓ 未知 (yfinance 無 firstTradeDate): {len(unknown_tids)} 檔")
    log(f"✅ 保留 (listed < 2025-08-29): {len(keep_tids)} 檔")

    # 列出被移除的（給主人 review）
    if remove_tids:
        log("\n=== 被移除清單 ===")
        for tid in remove_tids:
            ld = listed[tid]
            log(f"  {tid}  listed: {ld.strftime('%Y-%m-%d') if ld else 'N/A'}")

    if unknown_tids:
        log("\n=== 未知（yfinance 沒 firstTradeDate，預設保留）===")
        for tid in unknown_tids:
            log(f"  {tid}")

    # 1. 更新 universe
    new_universe = universe[~universe["tid"].isin(remove_tids)].copy()
    new_universe.to_csv(DATA_DIR / "etf_universe_raw.csv", index=False, encoding="utf-8-sig")
    log(f"\n💾 Universe: {len(universe)} → {len(new_universe)} ({len(remove_tids)} 移除)")

    # 2. 更新 blank
    new_blank = blank[blank["tid"].isin(keep_tids)].copy()
    new_blank.to_csv(OUT_DIR / "single_metrics_blank.csv", index=False, encoding="utf-8-sig")
    log(f"💾 Blank: {len(blank)} → {len(new_blank)} ({len(remove_tids)} 移除)")

    # 3. 更新 all（從 all 移除也避免 phase 3 再算到）
    all_csv = OUT_DIR / "single_metrics_all.csv"
    if all_csv.exists():
        df_all = pd.read_csv(all_csv)
        df_all_new = df_all[~df_all["tid"].isin(remove_tids)].copy()
        df_all_new.to_csv(all_csv, index=False, encoding="utf-8-sig")
        log(f"💾 All: {len(df_all)} → {len(df_all_new)}")

    # 4. 更新 filtered（不影響，但安全起見）
    for f in ["single_metrics_filtered.csv"]:
        fp = OUT_DIR / f
        if fp.exists():
            df = pd.read_csv(fp)
            new_df = df[~df["tid"].isin(remove_tids)]
            new_df.to_csv(fp, index=False, encoding="utf-8-sig")
            log(f"💾 {f}: {len(df)} → {len(new_df)}")

    # 摘要
    summary = {
        "cutoff": CUTOFF.strftime("%Y-%m-%d"),
        "blank_before": len(blank),
        "blank_after": len(new_blank),
        "universe_before": len(universe),
        "universe_after": len(new_universe),
        "removed_count": len(remove_tids),
        "removed_tids": remove_tids,
        "removed_dates": {tid: listed[tid].strftime("%Y-%m-%d") for tid in remove_tids},
        "unknown_tids": unknown_tids,
    }
    (LOG_DIR / "phase2_cleanup_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    log(f"\n💾 摘要: {LOG_DIR}/phase2_cleanup_summary.json")


if __name__ == "__main__":
    main()
