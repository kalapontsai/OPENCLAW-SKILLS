#!/usr/bin/env python3
"""
fund-plan Phase 2 v3: Multi-source fallback
- Primary: Flask server price_cache (instant)
- Secondary: yfinance retry+delay
- Dividend yield: MoneyDJ web fetch

Owner instruction #5045: prioritize Phase 2 completion, 600/hr FinMind OK,
rescreen 247 failed tickers, web search as fallback.
"""
import os, sys, json, time, re
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

LOG_FILE = LOG_DIR / "phase2_v3.log"
ALL_CSV = OUT_DIR / "single_metrics_all.csv"
BLANK_CSV = OUT_DIR / "single_metrics_blank.csv"
FILT_CSV = OUT_DIR / "single_metrics_filtered.csv"

START_DATE = pd.Timestamp("2019-01-01")
END_DATE = pd.Timestamp("2024-12-31")
RF = 0.015

THRESH = {
    "cagr": 0.03,
    "mdd": -0.30,
    "vol": 0.25,
    "sharpe": 0.5,
    "div_yield": 0.02,
}
METRIC_COLS = ["cagr", "mdd", "vol", "sharpe", "div_yield"]

FLASK_CACHE = Path("/mnt/d/stock/retrocast/data/price_cache")

# 上一輪 v2 結果（含 19 OK + 247 blank），避免重抓已成功的
V2_CSV = OUT_DIR / "single_metrics_all.csv"


def log(msg):
    ts = time.strftime("%H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line, flush=True)
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(line + "\n")


# ============================================================
# 1. Flask cache 讀取
# ============================================================
def fetch_flask_cache(tid: str):
    """讀 Flask server 本地 cache，回傳 (prices Series, status)"""
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
        if len(df) < 250:
            return None, "insufficient_range"
        return df["close"].astype(float), "ok"
    except Exception as e:
        return None, f"err:{type(e).__name__}"


# ============================================================
# 2. yfinance retry
# ============================================================
def fetch_yfinance(tid: str, max_retry: int = 3):
    """yfinance 重抓，含 retry + exponential backoff"""
    for attempt in range(1, max_retry + 1):
        try:
            df = yf.download(
                f"{tid}.TW",
                start="2019-01-01", end="2024-12-31",
                progress=False, auto_adjust=False, threads=False,
            )
            if df is None or len(df) < 250:
                time.sleep(2 ** attempt)
                continue
            # Flatten MultiIndex columns
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)

            t = yf.Ticker(f"{tid}.TW")
            divs = t.dividends
            if divs is not None and len(divs) > 0:
                if not isinstance(divs.index, pd.DatetimeIndex):
                    divs.index = pd.to_datetime(divs.index)
                divs = divs[(divs.index >= START_DATE) & (divs.index <= END_DATE)]
            else:
                divs = pd.Series(dtype=float)
            return df["Close"].astype(float), divs, "ok"
        except Exception:
            time.sleep(2 ** attempt)
    return None, None, "yfinance_fail"


# ============================================================
# 3. MoneyDJ 配息率（殖利率）
# ============================================================
def fetch_moneydj_yield(tid: str):
    """從 MoneyDJ 抓 殖利率（配息率）"""
    try:
        url = f"https://www.moneydj.com/etf/x/basic/basic0003.xdjhtm?etfid={tid}.TW"
        r = requests.get(url, timeout=10, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        })
        if r.status_code != 200:
            return None
        text = r.text
        # 殖利率後面通常接 %，抓第一個匹配
        m = re.search(r"殖利率[^<\d]*?([\d.]+)\s*%", text)
        if m:
            val = float(m.group(1))
            return val / 100 if val > 1 else val  # >1 假設是百分比
        return None
    except Exception:
        return None


# ============================================================
# 4. 計算 4 指標（CAGR / MDD / Vol / Sharpe）
# ============================================================
def calc_metrics(prices: pd.Series):
    try:
        prices = prices.dropna()
        if len(prices) < 250:
            return None
        if isinstance(prices, pd.DataFrame):
            prices = prices.iloc[:, 0]

        p_start = float(prices.iloc[0])
        p_end = float(prices.iloc[-1])
        n_days = (prices.index[-1] - prices.index[0]).days
        n_years = n_days / 365.25
        if p_start <= 0 or n_years < 1:
            return None

        cagr = (p_end / p_start) ** (1 / n_years) - 1

        peak = prices.cummax()
        drawdown = (prices - peak) / peak
        mdd = float(drawdown.min())

        daily_ret = prices.pct_change().dropna()
        vol = float(daily_ret.std(ddof=1) * np.sqrt(252))

        # Sharpe（Phase 2 用，不扣 Rf — 與 Flask server 一致）
        sharpe = float((daily_ret.mean() / daily_ret.std(ddof=1)) * np.sqrt(252)) if daily_ret.std(ddof=1) > 0 else 0.0

        return {
            "cagr": round(cagr, 4),
            "mdd": round(mdd, 4),
            "vol": round(vol, 4),
            "sharpe": round(sharpe, 4),
        }
    except Exception as e:
        log(f"  calc_metrics err: {e}")
        return None


# ============================================================
# Main
# ============================================================
def main():
    log("=" * 60)
    log("🚀 Phase 2 v3 — Multi-source (Flask cache + yfinance + MoneyDJ)")
    log("=" * 60)

    universe = pd.read_csv(DATA_DIR / "etf_universe_raw.csv")
    log(f"📊 候選池: {len(universe)} 檔")

    rows = []
    stats = {
        "flask_ok": 0,
        "yfinance_ok": 0,
        "blank": 0,
        "blank_reasons": {},
        "moneydj_yield_ok": 0,
        "yfinance_div_ok": 0,
    }

    for i, row in universe.iterrows():
        tid = str(row["tid"]).strip()
        name = str(row["name"]).strip()
        category = str(row["category"]).strip()

        if i % 10 == 0 or i == len(universe) - 1:
            log(f"⏳ {i+1}/{len(universe)} — {tid} {name}")

        prices = None
        divs = None
        source = None
        fetch_status = None

        # 1. Flask cache first
        p, status = fetch_flask_cache(tid)
        if p is not None:
            prices = p
            source = "flask_cache"
            stats["flask_ok"] += 1
            fetch_status = status
        else:
            fetch_status = status
            # 2. yfinance fallback
            p, d, status = fetch_yfinance(tid, max_retry=3)
            if p is not None:
                prices = p
                divs = d
                source = "yfinance"
                stats["yfinance_ok"] += 1
                fetch_status = status
            time.sleep(0.5)  # yfinance polite delay

        # 3. 計算 4 指標
        m = calc_metrics(prices) if prices is not None else None

        if m is None:
            stats["blank"] += 1
            stats["blank_reasons"][fetch_status or "unknown"] = stats["blank_reasons"].get(fetch_status or "unknown", 0) + 1
            rows.append({
                "tid": tid, "name": name, "category": category,
                "cagr": None, "mdd": None, "vol": None, "sharpe": None, "div_yield": None,
                "_source": "blank",
            })
            continue

        # 4. 配息率
        div_yield = None
        if divs is not None and len(divs) > 0:
            annual_div = float(divs.sum()) / 5
            avg_price = float(prices.mean())
            if avg_price > 0:
                div_yield = round(annual_div / avg_price, 4)
                stats["yfinance_div_ok"] += 1

        if div_yield is None:
            # 從 MoneyDJ 抓
            y = fetch_moneydj_yield(tid)
            if y is not None:
                div_yield = round(y, 4)
                stats["moneydj_yield_ok"] += 1
            time.sleep(0.3)

        rows.append({
            "tid": tid, "name": name, "category": category,
            **m,
            "div_yield": div_yield,
            "_source": source,
        })

        # 增量寫入（每 20 筆 flush 一次）
        if i % 20 == 0 and i > 0:
            pd.DataFrame(rows).to_csv(ALL_CSV, index=False, encoding="utf-8-sig")

    # 最終寫入
    df_all = pd.DataFrame(rows)
    df_all.to_csv(ALL_CSV, index=False, encoding="utf-8-sig")
    log(f"💾 {ALL_CSV}")

    # �選
    metric_ok = df_all.dropna(subset=METRIC_COLS).copy()
    df_filt = metric_ok[
        (metric_ok["cagr"] > THRESH["cagr"]) &
        (metric_ok["mdd"] > THRESH["mdd"]) &
        (metric_ok["vol"] < THRESH["vol"]) &
        (metric_ok["sharpe"] > THRESH["sharpe"]) &
        (metric_ok["div_yield"] > THRESH["div_yield"])
    ].copy()
    df_filt.drop(columns=["_source"]).to_csv(FILT_CSV, index=False, encoding="utf-8-sig")
    df_filt[["tid", "name", "category"]].to_csv(
        DATA_DIR / "etf_universe_filtered.csv", index=False, encoding="utf-8-sig"
    )

    # 留白清單
    blanks = df_all[df_all["_source"] == "blank"][["tid", "name", "category"]]
    blanks.to_csv(BLANK_CSV, index=False, encoding="utf-8-sig")

    log("=" * 60)
    log(f"📊 結果:")
    log(f"  Flask cache OK:    {stats['flask_ok']}")
    log(f"  yfinance OK:       {stats['yfinance_ok']}")
    log(f"  Blank:             {stats['blank']} ({stats['blank_reasons']})")
    log(f"  MoneyDJ 殖利率 OK: {stats['moneydj_yield_ok']}")
    log(f"  yfinance 配息 OK:  {stats['yfinance_div_ok']}")
    log(f"  通過 5 門檻:        {len(df_filt)}")
    log("=" * 60)

    if len(df_filt) > 0:
        top = df_filt.sort_values("sharpe", ascending=False).head(20)
        log("🏆 Top 20 (by Sharpe):")
        for _, r in top.iterrows():
            log(f"  {r['tid']} {r['name']} | Sharpe {r['sharpe']:.2f} CAGR {r['cagr']:.2%} MDD {r['mdd']:.1%} Vol {r['vol']:.1%} Div {r['div_yield']:.2%}")

    summary = {
        "total": len(rows),
        "flask_ok": stats["flask_ok"],
        "yfinance_ok": stats["yfinance_ok"],
        "blank": stats["blank"],
        "blank_reasons": stats["blank_reasons"],
        "moneydj_yield_ok": stats["moneydj_yield_ok"],
        "yfinance_div_ok": stats["yfinance_div_ok"],
        "filtered": len(df_filt),
        "top_5_tids": df_filt.sort_values("sharpe", ascending=False).head(5)["tid"].tolist() if len(df_filt) > 0 else [],
    }
    (LOG_DIR / "phase2_v3_summary.json").write_text(
        pd.Series(summary).to_json(force_ascii=False, indent=2),
        encoding="utf-8",
    )
    log(f"💾 摘要：{LOG_DIR}/phase2_v3_summary.json")


if __name__ == "__main__":
    main()
