#!/usr/bin/env python3
"""
fund-plan Phase 2 v5: Extend - handle edge cases (low rows, suffix variations)
"""
import os, sys, json, time, csv
from pathlib import Path
import numpy as np
import pandas as pd
import yfinance as yf
import requests
import io

PROJECT_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_DIR / "data"
OUT_DIR = PROJECT_DIR / "outputs"
LOG_DIR = PROJECT_DIR / "logs"

LOG_FILE = LOG_DIR / "phase2_v5_extend.log"
ALL_CSV = OUT_DIR / "single_metrics_all.csv"
FILT_CSV = OUT_DIR / "single_metrics_filtered.csv"
YIELD_CSV = DATA_DIR / "dividend" / "etfinfo_yields.csv"

THRESH = {"cagr": 0.03, "mdd": -0.30, "vol": 0.25, "sharpe": 0.5, "div_yield": 0.02}
METRIC_COLS = ["cagr", "mdd", "vol", "sharpe", "div_yield"]

START_DATE = pd.Timestamp("2019-01-01")
END_DATE = pd.Timestamp("2024-12-31")

FLASK_CACHE = Path("/mnt/d/stock/retrocast/data/price_cache")


def log(msg):
    ts = time.strftime("%H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line, flush=True)
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def load_yields():
    yields = {}
    if not YIELD_CSV.exists():
        return yields
    with open(YIELD_CSV, encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            ty = r["trailingYield"]
            if ty and ty != "":
                try:
                    yields[r["code"]] = float(ty) / 100
                except ValueError:
                    pass
    return yields


def fetch_yfinance_aggressive(tid, min_rows=50, timeout=10):
    """yfinance with all suffix variants + lower min_rows threshold"""
    is_bond = tid.endswith('B') or tid.endswith('C') or '債' in tid
    
    # Try multiple suffix variations
    suffixes = []
    if is_bond:
        suffixes = [f"{tid}.TWO", f"{tid}.TW", f"{tid}.two", f"{tid}.tw"]
    else:
        suffixes = [f"{tid}.TW", f"{tid}.TWO", f"{tid}.tw", f"{tid}.two"]
    
    best_df = None
    best_suffix = None
    best_rows = 0
    
    for sym in suffixes:
        try:
            sys.stderr = io.StringIO()
            import signal
            def handler(signum, frame):
                raise TimeoutError("yfinance timeout")
            signal.signal(signal.SIGALRM, handler)
            signal.alarm(timeout)
            
            df = yf.download(
                sym, start="2019-01-01", end="2024-12-31",
                progress=False, auto_adjust=False, threads=False,
            )
            signal.alarm(0)
            sys.stderr = sys.__stderr__
            
            if df is None or len(df) < min_rows:
                continue
            
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)
            close = df["Close"]
            if isinstance(close, pd.DataFrame):
                close = close.iloc[:, 0]
            close = close.astype(float).dropna()
            if len(close) >= min_rows:
                if len(close) > best_rows:
                    best_df = close
                    best_suffix = sym.replace(tid, '')
                    best_rows = len(close)
        except (TimeoutError, Exception):
            sys.stderr = sys.__stderr__
            signal.alarm(0)
            continue
    
    if best_df is not None:
        return best_df, f"yfinance{best_suffix}"
    return None, "yfinance_fail"


def fetch_flask_cache(tid):
    p = FLASK_CACHE / f"{tid}.json"
    if not p.exists():
        return None, "no_cache"
    try:
        with open(p, encoding="utf-8") as f:
            data = json.load(f)
        rows = data.get("rows", [])
        if not rows:
            return None, "empty_cache"
        df = pd.DataFrame(rows)
        df["date"] = pd.to_datetime(df["date"])
        df = df.set_index("date").sort_index()
        df = df[(df.index >= START_DATE) & (df.index <= END_DATE)]
        if len(df) < 50:
            return None, f"insufficient({len(df)})"
        return df["close"].astype(float), "ok"
    except Exception as e:
        return None, f"err:{type(e).__name__}"


def calc_metrics(prices):
    try:
        prices = prices.dropna()
        if isinstance(prices, pd.DataFrame):
            prices = prices.iloc[:, 0]
        prices = prices[~prices.index.duplicated(keep='first')].sort_index()

        if len(prices) < 50:
            return None

        p_start = float(prices.iloc[0])
        p_end = float(prices.iloc[-1])
        n_days = (prices.index[-1] - prices.index[0]).days
        n_years = n_days / 365.25

        if p_start <= 0 or n_years < 0.3:
            return None

        cagr = (p_end / p_start) ** (1 / n_years) - 1
        peak = prices.cummax()
        drawdown = (prices - peak) / peak
        mdd = float(drawdown.min())
        daily_ret = prices.pct_change().dropna()
        if len(daily_ret) < 20:
            return None
        vol = float(daily_ret.std(ddof=1) * np.sqrt(252))
        sharpe = float((daily_ret.mean() / daily_ret.std(ddof=1)) * np.sqrt(252)) \
            if daily_ret.std(ddof=1) > 0 else 0.0

        return {
            "cagr": round(cagr, 4),
            "mdd": round(mdd, 4),
            "vol": round(vol, 4),
            "sharpe": round(sharpe, 4),
            "n_years": round(n_years, 2),
        }
    except Exception:
        return None


def main():
    log("=" * 60)
    log("🚀 Phase 2 v5 Extend — handle edge cases")
    log("=" * 60)

    df = pd.read_csv(ALL_CSV)
    log(f"📊 現有: {len(df)} 檔")
    log(f"   5 指標完整: {df[METRIC_COLS].notna().all(axis=1).sum()}")

    yields = load_yields()
    log(f"📂 etfinfo yields: {len(yields)}")

    to_process = df[df["_source"] == "blank"].copy()
    log(f"📝 待處理 (blank): {len(to_process)}")

    stats = {"price_added": 0, "still_blank": 0, "blank_by_cat": {}}

    for i, (idx, row) in enumerate(to_process.iterrows()):
        tid = str(row["tid"]).strip()
        category = str(row["category"]).strip()

        if i % 10 == 0:
            log(f"⏳ {i+1}/{len(to_process)} — {tid} ({category})")

        # Try aggressive yfinance
        prices, source_price = fetch_yfinance_aggressive(tid, min_rows=50, timeout=8)
        if prices is None:
            prices, source_price = fetch_flask_cache(tid)

        if prices is None:
            stats["still_blank"] += 1
            stats["blank_by_cat"][category] = stats["blank_by_cat"].get(category, 0) + 1
            continue

        m = calc_metrics(prices)
        if m is None:
            stats["still_blank"] += 1
            stats["blank_by_cat"][category] = stats["blank_by_cat"].get(category, 0) + 1
            continue

        y = yields.get(tid)
        stats["price_added"] += 1

        df.at[idx, "cagr"] = m["cagr"]
        df.at[idx, "mdd"] = m["mdd"]
        df.at[idx, "vol"] = m["vol"]
        df.at[idx, "sharpe"] = m["sharpe"]
        if y is not None:
            df.at[idx, "div_yield"] = round(y, 4)
        df.at[idx, "_source"] = source_price + ("+yield" if y else "")

        # 增量寫入
        if (i + 1) % 10 == 0:
            df.to_csv(ALL_CSV, index=False, encoding="utf-8-sig")
            log(f"   💾 {stats}")

        time.sleep(0.1)

    df.to_csv(ALL_CSV, index=False, encoding="utf-8-sig")

    log("=" * 60)
    log(f"📊 Extend 結果:")
    log(f"  Price added: {stats['price_added']}")
    log(f"  Still blank: {stats['still_blank']}")
    log(f"  Blank by cat: {stats['blank_by_cat']}")
    log(f"  總 5 指標完整: {df[METRIC_COLS].notna().all(axis=1).sum()}")

    # Apply 5 thresholds
    metric_ok = df.dropna(subset=METRIC_COLS).copy()
    df_filt = metric_ok[
        (metric_ok["cagr"] > THRESH["cagr"]) &
        (metric_ok["mdd"] > THRESH["mdd"]) &
        (metric_ok["vol"] < THRESH["vol"]) &
        (metric_ok["sharpe"] > THRESH["sharpe"]) &
        (metric_ok["div_yield"] > THRESH["div_yield"])
    ].copy()
    log(f"🏆 通過 5 門檻: {len(df_filt)}")

    df_filt[["tid","name","category","cagr","mdd","vol","sharpe","div_yield","_source"]].to_csv(
        FILT_CSV, index=False, encoding="utf-8-sig")
    log(f"💾 {FILT_CSV}")

    log("🏆 Top 20 (by Sharpe):")
    top = df_filt.sort_values("sharpe", ascending=False).head(20)
    for _, r in top.iterrows():
        log(f"  {r['tid']} {r['name']} | Shar {r['sharpe']:.2f} CAGR {r['cagr']:.2%} MDD {r['mdd']:.1%} Vol {r['vol']:.1%} Div {r['div_yield']:.2%}")

    # Summary
    summary = {
        "phase": "v5_extend",
        "total": len(df),
        "complete_5": int(df[METRIC_COLS].notna().all(axis=1).sum()),
        "pass_5_thresh": len(df_filt),
        "blank": int((df["_source"] == "blank").sum()),
        "blank_by_cat": stats["blank_by_cat"],
        "top_5": df_filt.sort_values("sharpe", ascending=False).head(5)[["tid","name","sharpe"]].to_dict('records'),
    }
    (LOG_DIR / "phase2_v5_extend_summary.json").write_text(
        pd.Series(summary).to_json(force_ascii=False, indent=2),
        encoding="utf-8",
    )
    log(f"💾 {LOG_DIR}/phase2_v5_extend_summary.json")


if __name__ == "__main__":
    main()
