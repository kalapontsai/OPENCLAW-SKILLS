#!/usr/bin/env python3
"""
fund-plan Phase 2 v5: 完成清單 (12 → 50+)

Strategy:
- 保留 v4 已有資料（flask_cache + yfinance）
- Group 1 (19 個有價格無殖利率): 從 MoneyDJ 多分類 + StockQ + etfinfo 重抓
- Group 2 (235 個完全無資料): yfinance 用 .TW/.TWO 重抓 + Flask cache
  - bond ETF (結尾 'B') 自動用 .TWO 後綴
  - n_years < 5 接受實際年數算 CAGR
- 增量寫入

Owner: 主人 #5054 — 「不判斷組合，持續補到完整」
"""
import os, sys, json, time, csv, re
from pathlib import Path
import numpy as np
import pandas as pd
import requests
import yfinance as yf

PROJECT_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_DIR / "data"
OUT_DIR = PROJECT_DIR / "outputs"
LOG_DIR = PROJECT_DIR / "logs"
for d in [DATA_DIR, OUT_DIR, LOG_DIR]:
    d.mkdir(parents=True, exist_ok=True)

LOG_FILE = LOG_DIR / "phase2_v5.log"
ALL_CSV = OUT_DIR / "single_metrics_all.csv"  # v4 → 升級 v5
FILT_CSV = OUT_DIR / "single_metrics_filtered.csv"
YIELD_CSV = DATA_DIR / "dividend" / "etfinfo_yields.csv"

# 5 thresholds（主人原始 5 條件，不放寬）
THRESH = {
    "cagr": 0.03,
    "mdd": -0.30,
    "vol": 0.25,
    "sharpe": 0.5,
    "div_yield": 0.02,
}
METRIC_COLS = ["cagr", "mdd", "vol", "sharpe", "div_yield"]

START_DATE = pd.Timestamp("2019-01-01")
END_DATE = pd.Timestamp("2024-12-31")
RF = 0.015

FLASK_CACHE = Path("/mnt/d/stock/retrocast/data/price_cache")
MIN_HISTORY_DAYS = 250  # ~1 year for new ETFs (relaxed from 250)


def log(msg):
    ts = time.strftime("%H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line, flush=True)
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(line + "\n")


# ============================================================
# Yield (殖利率) 載入
# ============================================================
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


def fetch_moneydj_yield(tid):
    """從 MoneyDJ 各分類 list 頁面找 殖利率"""
    for c in [47, 4, 15, 2, 6, 8, 3, 5, 7]:
        url = f"https://www.moneydj.com/etf/eb/et305001list.djhtm?R=500&order=4&C={c}"
        try:
            r = requests.get(url, timeout=10, headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            })
            if r.status_code != 200 or len(r.text) < 5000:
                continue
            text = r.text
            for m in re.finditer(r'<tr[^>]*>(.+?)</tr>', text, re.DOTALL):
                row = m.group(1)
                tds = re.findall(r'<td[^>]*>(.*?)</td>', row, re.DOTALL)
                if len(tds) < 10:
                    continue
                code_m = re.search(r'etfid=(\w+)\.TW', tds[0])
                if not code_m or code_m.group(1) != tid:
                    continue
                cleaned = []
                for td in tds:
                    clean = re.sub(r'<[^>]+>', '', td).strip()
                    cleaned.append(clean)
                # 殖利率在倒數第 3 欄（C=47 確認過 [9] 是殖利率）
                for i in [-3, -2, -1, 9, 8, 10]:
                    if abs(i) <= len(cleaned):
                        val = cleaned[i]
                        if val and val != 'N/A':
                            try:
                                y = float(val.replace(',', ''))
                                if 0 < y < 30:  # 合理範圍
                                    return y / 100
                            except ValueError:
                                pass
        except Exception:
            pass
        time.sleep(0.3)
    return None


# ============================================================
# Price fetchers
# ============================================================
def fetch_flask_cache(tid):
    """從 Flask server 本地 cache 讀"""
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
        if len(df) < 100:  # 寬鬆一點，新 ETF 也要能算
            return None, f"insufficient_range({len(df)})"
        return df["close"].astype(float), "ok"
    except Exception as e:
        return None, f"err:{type(e).__name__}"


def fetch_yfinance(tid, max_retry=1, sleep=0.3):
    """yfinance 重抓，含 .TW/.TWO 兩種後綴 + retry（fail-fast）"""
    import io, sys
    is_bond = tid.endswith('B') or tid.endswith('-B')
    suffixes = ['.TWO', '.TW'] if is_bond else ['.TW', '.TWO']

    # Suppress noisy yfinance stderr
    old_stderr = sys.stderr
    try:
        for suffix in suffixes:
            try:
                # Suppress stderr during download (yfinance prints errors)
                sys.stderr = io.StringIO()
                df = yf.download(
                    f"{tid}{suffix}",
                    start="2019-01-01", end="2024-12-31",
                    progress=False, auto_adjust=False, threads=False,
                )
                sys.stderr = old_stderr
                if df is None or len(df) < 100:
                    continue
                # Flatten MultiIndex
                if isinstance(df.columns, pd.MultiIndex):
                    df.columns = df.columns.get_level_values(0)
                # Ensure 'Close' is series not DataFrame
                close = df["Close"]
                if isinstance(close, pd.DataFrame):
                    close = close.iloc[:, 0]
                close = close.astype(float).dropna()
                if len(close) < 100:
                    continue
                return close, f"yfinance_{suffix}"
            except Exception:
                sys.stderr = old_stderr
                continue
        sys.stderr = old_stderr
    except Exception:
        sys.stderr = old_stderr
    return None, "yfinance_fail"


# ============================================================
# Metrics
# ============================================================
def calc_metrics(prices: pd.Series):
    """計算 4 指標（CAGR/MDD/Vol/Sharpe）
    接受 n_years < 5 的新 ETF
    """
    try:
        prices = prices.dropna()
        if isinstance(prices, pd.DataFrame):
            prices = prices.iloc[:, 0]
        prices = prices[~prices.index.duplicated(keep='first')].sort_index()

        if len(prices) < 100:
            return None

        p_start = float(prices.iloc[0])
        p_end = float(prices.iloc[-1])
        n_days = (prices.index[-1] - prices.index[0]).days
        n_years = n_days / 365.25

        if p_start <= 0 or n_years < 0.5:  # 至少半年資料
            return None

        cagr = (p_end / p_start) ** (1 / n_years) - 1

        peak = prices.cummax()
        drawdown = (prices - peak) / peak
        mdd = float(drawdown.min())

        daily_ret = prices.pct_change().dropna()
        if len(daily_ret) < 30:
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
    except Exception as e:
        return None


# ============================================================
# Main
# ============================================================
def main():
    log("=" * 60)
    log("🚀 Phase 2 v5 — 完成清單 (12 → 50+)")
    log("=" * 60)

    # 載入 v4 結果
    df_v4 = pd.read_csv(ALL_CSV)
    log(f"📊 v4 既有: {len(df_v4)} 檔")
    log(f"   flask_cache: {(df_v4['_source']=='flask_cache').sum()}")
    log(f"   yfinance: {(df_v4['_source']=='yfinance').sum()}")
    log(f"   blank: {(df_v4['_source']=='blank').sum()}")
    log(f"   有完整 5 指標: {df_v4[METRIC_COLS].notna().all(axis=1).sum()}")

    # 載入既有殖利率（etfinfo.tw）
    yields = load_yields()
    log(f"📂 etfinfo.tw yields: {len(yields)} 筆")

    rows = []
    stats = {
        "kept_existing": 0,
        "v4_with_4_metrics": 0,
        "g1_yield_added": 0,  # Group 1: 補殖利率
        "g2_price_added": 0,  # Group 2a: 補價格
        "g2b_both_added": 0,  # Group 2b: 補價格+殖利率
        "still_blank": 0,
        "blank_reasons": {},
    }

    # 先用 Flask cache 預載一些新 ETF（009805 等）
    # 這些 yfinance 沒有但 Flask cache 有
    flask_cache_extra = ['009805', '00980A', '009816', '00981A', '00988A']

    for i, row in df_v4.iterrows():
        tid = str(row["tid"]).strip()
        name = str(row["name"]).strip()
        category = str(row["category"]).strip()
        source_v4 = str(row["_source"]).strip()
        div_yield_v4 = row["div_yield"]

        # Case A: v4 已有完整 5 指標 → 保留
        if source_v4 in ("flask_cache", "yfinance") and pd.notna(row.get("div_yield")):
            rows.append({
                "tid": tid, "name": name, "category": category,
                "cagr": row["cagr"], "mdd": row["mdd"], "vol": row["vol"],
                "sharpe": row["sharpe"], "div_yield": row["div_yield"],
                "_source": source_v4,
            })
            stats["kept_existing"] += 1
            continue

        # Case B: v4 有 4 指標無殖利率 (Group 1: 19 ETFs)
        if source_v4 in ("flask_cache", "yfinance") and pd.isna(row.get("div_yield")):
            # 嘗試找殖利率
            y = yields.get(tid)
            if y is None:
                y = fetch_moneydj_yield(tid)
            if y is not None:
                div_yield_v4 = round(y, 4)
                stats["g1_yield_added"] += 1
                log(f"  ✅ G1 yield added: {tid} {name} = {div_yield_v4:.4f}")
            rows.append({
                "tid": tid, "name": name, "category": category,
                "cagr": row["cagr"], "mdd": row["mdd"], "vol": row["vol"],
                "sharpe": row["sharpe"], "div_yield": div_yield_v4,
                "_source": source_v4 + ("+yield" if div_yield_v4 == div_yield_v4 else ""),
            })
            continue

        # Case C: v4 完全 blank (Group 2)
        # 嘗試 yfinance → flask cache
        prices, source_price = fetch_yfinance(tid, max_retry=2)
        if prices is None and tid in flask_cache_extra:
            prices, source_price = fetch_flask_cache(tid)
        if prices is None:
            # 再 try flask cache 一般
            prices, source_price = fetch_flask_cache(tid)

        if prices is None:
            stats["still_blank"] += 1
            stats["blank_reasons"][source_price] = stats["blank_reasons"].get(source_price, 0) + 1
            rows.append({
                "tid": tid, "name": name, "category": category,
                "cagr": None, "mdd": None, "vol": None, "sharpe": None, "div_yield": None,
                "_source": "blank",
            })
            continue

        # 計算指標
        m = calc_metrics(prices)
        if m is None:
            stats["still_blank"] += 1
            stats["blank_reasons"]["calc_fail"] = stats["blank_reasons"].get("calc_fail", 0) + 1
            rows.append({
                "tid": tid, "name": name, "category": category,
                "cagr": None, "mdd": None, "vol": None, "sharpe": None, "div_yield": None,
                "_source": "blank",
            })
            continue

        # 殖利率
        y = yields.get(tid)
        if y is None:
            y = fetch_moneydj_yield(tid)

        if y is not None:
            stats["g2_price_added"] += 1
        else:
            stats["g2b_both_added"] += 1  # 有價格但無殖利率

        rows.append({
            "tid": tid, "name": name, "category": category,
            "cagr": m["cagr"], "mdd": m["mdd"], "vol": m["vol"],
            "sharpe": m["sharpe"], "div_yield": round(y, 4) if y else None,
            "_source": source_price + ("+yield" if y else ""),
        })

        if (i + 1) % 10 == 0:
            log(f"⏳ {i+1}/{len(df_v4)} — done. kept={stats['kept_existing']} G1={stats['g1_yield_added']} G2={stats['g2_price_added']} blank={stats['still_blank']}")
            # 增量寫入
            pd.DataFrame(rows).to_csv(ALL_CSV, index=False, encoding="utf-8-sig")

        time.sleep(0.2)  # yfinance polite (reduced)

    # 最終寫入
    df_all = pd.DataFrame(rows)
    df_all.to_csv(ALL_CSV, index=False, encoding="utf-8-sig")
    log(f"💾 {ALL_CSV} ({len(df_all)} rows)")

    # === 統計 ===
    log("=" * 60)
    log(f"📊 結果:")
    log(f"  保留 v4:         {stats['kept_existing']}")
    log(f"  G1 補殖利率:     {stats['g1_yield_added']}")
    log(f"  G2 補價格+殖利率: {stats['g2_price_added']}")
    log(f"  G2b 有價格無殖利率: {stats['g2b_both_added']}")
    log(f"  仍 blank:        {stats['still_blank']} ({stats['blank_reasons']})")
    log(f"  總計:             {len(df_all)}")

    # === 5 指標完整 ===
    metric_ok = df_all.dropna(subset=METRIC_COLS).copy()
    log(f"📐 5 指標皆齊: {len(metric_ok)} 檔")
    log(f"   vs v4: 12 → v5: {len(metric_ok)}")

    # === 5 門檻 ===
    df_filt = metric_ok[
        (metric_ok["cagr"] > THRESH["cagr"]) &
        (metric_ok["mdd"] > THRESH["mdd"]) &
        (metric_ok["vol"] < THRESH["vol"]) &
        (metric_ok["sharpe"] > THRESH["sharpe"]) &
        (metric_ok["div_yield"] > THRESH["div_yield"])
    ].copy()
    log(f"🏆 通過 5 門檻: {len(df_filt)} 檔")

    cols_out = [c for c in ["tid","name","category","cagr","mdd","vol","sharpe","div_yield","_source"] if c in df_filt.columns]
    df_filt[cols_out].to_csv(FILT_CSV, index=False, encoding="utf-8-sig")
    log(f"💾 {FILT_CSV}")

    df_filt[["tid","name","category"]].to_csv(
        DATA_DIR / "etf_universe_filtered.csv", index=False, encoding="utf-8-sig"
    )
    log(f"💾 data/etf_universe_filtered.csv")

    # === Top 20 ===
    if len(df_filt) > 0:
        log("🏆 Top 20 (by Sharpe):")
        top = df_filt.sort_values("sharpe", ascending=False).head(20)
        for _, r in top.iterrows():
            log(f"  {r['tid']} {r['name']} | Shar {r['sharpe']:.2f} CAGR {r['cagr']:.2%} MDD {r['mdd']:.1%} Vol {r['vol']:.1%} Div {r['div_yield']:.2%}")

    # === 4 條件通過 + 殖利率分佈 ===
    df_4 = metric_ok[
        (metric_ok["cagr"] > THRESH["cagr"]) &
        (metric_ok["mdd"] > THRESH["mdd"]) &
        (metric_ok["vol"] < THRESH["vol"]) &
        (metric_ok["sharpe"] > THRESH["sharpe"])
    ].copy()
    log(f"📊 4 條件通過: {len(df_4)}")
    if len(df_4) > 0:
        log(f"  殖利率分佈:")
        for thr_label, thr in [(">= 1%", 0.01), (">= 2%", 0.02), (">= 3%", 0.03), (">= 5%", 0.05)]:
            count = (df_4["div_yield"] >= thr).sum()
            log(f"    {thr_label}: {count}")

    # 摘要 JSON
    summary = {
        "phase": "v5",
        "total_universe": len(df_all),
        "v4_complete_5": 12,
        "v5_complete_5": int(df_all[METRIC_COLS].notna().all(axis=1).sum()),
        "v5_pass_5_thresh": len(df_filt),
        "stats": stats,
        "top_5_tids": df_filt.sort_values("sharpe", ascending=False).head(5)["tid"].tolist() if len(df_filt) > 0 else [],
    }
    (LOG_DIR / "phase2_v5_summary.json").write_text(
        pd.Series(summary).to_json(force_ascii=False, indent=2),
        encoding="utf-8",
    )
    log(f"💾 {LOG_DIR}/phase2_v5_summary.json")
    log("=" * 60)


if __name__ == "__main__":
    main()
