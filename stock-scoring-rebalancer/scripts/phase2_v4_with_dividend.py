#!/usr/bin/env python3
"""
fund-plan Phase 2 v4: Add dividend yield via etfinfo.tw

Strategy:
- Reuse existing 4-metric data from phase2_calculate_metrics.py outputs
- Load pre-fetched yields from data/dividend/etfinfo_yields.csv (saved from this run)
- Filter using 5 thresholds

Owner: 主人 expected yields in 5-threshold filter. v3 had 0/31 because MoneyDJ JS-rendered.
v4: pre-fetched from etfinfo.tw (Nuxt SSR data, server-side).
"""
import os, sys, json, time, csv
from pathlib import Path
import numpy as np
import pandas as pd

PROJECT_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_DIR / "data"
OUT_DIR = PROJECT_DIR / "outputs"
LOG_DIR = PROJECT_DIR / "logs"
for d in [DATA_DIR, OUT_DIR, LOG_DIR]:
    d.mkdir(parents=True, exist_ok=True)

LOG_FILE = LOG_DIR / "phase2_v4.log"
ALL_CSV = OUT_DIR / "single_metrics_all.csv"
FILT_CSV = OUT_DIR / "single_metrics_filtered.csv"
YIELD_CSV = DATA_DIR / "dividend" / "etfinfo_yields.csv"

# 5 thresholds (主人 original 5 conditions)
THRESH = {
    "cagr": 0.03,      # > 3%
    "mdd": -0.30,      # > -30% (less negative)
    "vol": 0.25,       # < 25%
    "sharpe": 0.5,     # > 0.5
    "div_yield": 0.02, # > 2%
}
METRIC_COLS = ["cagr", "mdd", "vol", "sharpe", "div_yield"]


def log(msg):
    ts = time.strftime("%H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line, flush=True)
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def load_yields():
    """從預抓的 etfinfo CSV 載入殖利率（百分比 → 小數）"""
    yields = {}
    if not YIELD_CSV.exists():
        log(f"⚠️  {YIELD_CSV} 不存在")
        return yields
    with open(YIELD_CSV, encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            ty = r["trailingYield"]
            if ty and ty != "":
                try:
                    # etfinfo 直接以 % 存（例：15.93 = 15.93%）→ 轉小數
                    yields[r["code"]] = float(ty) / 100
                except ValueError:
                    pass
    log(f"📂 載入 {len(yields)} 筆殖利率")
    return yields


def main():
    log("=" * 60)
    log("🚀 Phase 2 v4 — 補殖利率 + 5 門檻")
    log("=" * 60)

    # 載入既有 4 指標
    df = pd.read_csv(ALL_CSV)
    log(f"📊 既有 4 指標: {len(df)} 檔")
    log(f"   有 cagr 資料: {df['cagr'].notna().sum()}")

    # 載入殖利率
    yields = load_yields()

    # 補殖利率
    new_div = []
    matched = 0
    for _, row in df.iterrows():
        tid = str(row["tid"]).strip()
        if tid in yields:
            new_div.append(round(yields[tid], 4))
            matched += 1
        else:
            new_div.append(None)
    df["div_yield"] = new_div
    log(f"✅ 配息率補齊: {matched} / {len(df)}")

    # 儲存更新後的 ALL CSV（含殖利率）
    df.to_csv(ALL_CSV, index=False, encoding="utf-8-sig")
    log(f"💾 更新 {ALL_CSV}")

    # 5 門檻篩選
    metric_ok = df.dropna(subset=METRIC_COLS).copy()
    log(f"📐 5 指標皆齊: {len(metric_ok)} 檔")

    df_filt = metric_ok[
        (metric_ok["cagr"] > THRESH["cagr"]) &
        (metric_ok["mdd"] > THRESH["mdd"]) &
        (metric_ok["vol"] < THRESH["vol"]) &
        (metric_ok["sharpe"] > THRESH["sharpe"]) &
        (metric_ok["div_yield"] > THRESH["div_yield"])
    ].copy()
    log(f"🏆 通過 5 門檻: {len(df_filt)}")

    # 4 條件通過（暫不看殖利率）
    df_4 = metric_ok[
        (metric_ok["cagr"] > THRESH["cagr"]) &
        (metric_ok["mdd"] > THRESH["mdd"]) &
        (metric_ok["vol"] < THRESH["vol"]) &
        (metric_ok["sharpe"] > THRESH["sharpe"])
    ].copy()
    log(f"📊 4 條件通過（CAGR/MDD/Vol/Sharpe）: {len(df_4)}")

    # 寫入篩選結果
    cols_out = [c for c in ["tid","name","category","cagr","mdd","vol","sharpe","div_yield","_source"] if c in df_filt.columns]
    df_filt[cols_out].to_csv(FILT_CSV, index=False, encoding="utf-8-sig")
    log(f"💾 {FILT_CSV} ({len(df_filt)} 筆)")

    # Universe pool
    df_filt[["tid","name","category"]].to_csv(
        DATA_DIR / "etf_universe_filtered.csv", index=False, encoding="utf-8-sig"
    )
    log(f"💾 data/etf_universe_filtered.csv")

    # Top 20
    if len(df_filt) > 0:
        log("🏆 Top 20 (by Sharpe):")
        top = df_filt.sort_values("sharpe", ascending=False).head(20)
        for _, r in top.iterrows():
            log(f"  {r['tid']} {r['name']} | Shar {r['sharpe']:.2f} CAGR {r['cagr']:.2%} MDD {r['mdd']:.1%} Vol {r['vol']:.1%} Div {r['div_yield']:.2%}")
    else:
        log("⚠️  0 通過 5 門檻")
        log("📊 4 條件通過 + 殖利率分佈：")
        log(f"  4 條件通過: {len(df_4)}")
        if len(df_4) > 0:
            d4 = df_4["div_yield"].dropna()
            if len(d4) > 0:
                log(f"  殖利率分佈 (4 條件通過):")
                log(f"    Min: {d4.min():.2%}, Median: {d4.median():.2%}, Max: {d4.max():.2%}")
                log(f"    >= 1%: {sum(d4 >= 0.01)}")
                log(f"    >= 2%: {sum(d4 >= 0.02)}")
                log(f"    >= 3%: {sum(d4 >= 0.03)}")
                log(f"    >= 5%: {sum(d4 >= 0.05)}")
            log("  Top 10 (by Sharpe):")
            top = df_4.sort_values("sharpe", ascending=False).head(10)
            for _, r in top.iterrows():
                log(f"    {r['tid']} {r['name']} | Shar {r['sharpe']:.2f} CAGR {r['cagr']:.2%} MDD {r['mdd']:.1%} Vol {r['vol']:.1%} Div {(r['div_yield'] or 0):.2%}")

    # 摘要
    summary = {
        "phase": "v4",
        "total_universe": len(df),
        "with_4_metrics": int(df[["cagr","mdd","vol","sharpe"]].notna().all(axis=1).sum()),
        "with_dividend_yield": matched,
        "filtered_5": len(df_filt),
        "filtered_4_no_div": len(df_4),
        "top_5_tids": df_filt.sort_values("sharpe", ascending=False).head(5)["tid"].tolist() if len(df_filt) > 0 else [],
    }
    (LOG_DIR / "phase2_v4_summary.json").write_text(
        pd.Series(summary).to_json(force_ascii=False, indent=2),
        encoding="utf-8",
    )
    log(f"💾 {LOG_DIR}/phase2_v4_summary.json")
    log("=" * 60)
    log(f"📊 摘要: 5 門檻 {len(df_filt)} 通過 / 4 條件 {len(df_4)} 通過")
    log("=" * 60)


if __name__ == "__main__":
    main()
