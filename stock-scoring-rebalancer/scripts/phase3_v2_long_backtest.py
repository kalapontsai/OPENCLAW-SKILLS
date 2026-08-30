#!/usr/bin/env python3
"""
fund-plan Phase 3 v2 — 加長回測期（3 年 + 5 年）+ 半年再平衡 + 交易成本 + bear + walk-forward

主人 #5082 + #5085 指示：
- Phase 3 v2：分組綜合分數都符合門檻 → Top 3 union → 加長回測期 → 重複 Phase 3, 4
- 兩窗口：3 年 (2023-08-29 ~ 2026-08-29, 9 檔) + 5 年 (2021-08-29 ~ 2026-08-29, 7 檔)
- 半年再平衡一次 (Feb + Aug 第 1 個交易日) + 0.57% 年化交易成本
- bear scenario + walk-forward

設計原則：
- 共用 v1 metric 公式（CAGR / Sharpe / Sortino / MDD / Calmar / total_return）
- 蒙地卡羅 Dirichlet α=2, 5-10 檔, 單檔 ≤ 35%
- 6 分數排名 + 總分（總分低 = 好）
- 跑完兩個窗口再輸出
"""
from __future__ import annotations
import sys, os, json, time, re
from pathlib import Path
import numpy as np
import pandas as pd
import yfinance as yf
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

plt.rcParams['font.sans-serif'] = ['Noto Sans CJK TC', 'WenQuanYi Micro Hei', 'DejaVu Sans']
plt.rcParams['axes.unicode_minus'] = False

PROJECT_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_DIR / "data"
OUT_DIR = PROJECT_DIR / "outputs"
LOG_DIR = PROJECT_DIR / "logs"
CACHE_DIR = DATA_DIR / "phase3v2_cache"

for d in [DATA_DIR, OUT_DIR, LOG_DIR, CACHE_DIR]:
    d.mkdir(parents=True, exist_ok=True)

LOG_FILE = LOG_DIR / "phase3_v2_phase4_v2.log"
SUMMARY_FILE = LOG_DIR / "phase3v2_phase4v2_summary.json"

RF = 0.02  # risk-free (與 v1 一致)

# ===== 9 檔 union（master 指定）=====
TOP9_UNION = [
    ("00881", "國泰台灣5G"),
    ("00935", "野村臺灣新科技50"),
    ("00690", "兆豐藍籌30"),
    ("00939", "統一台灣高息動能"),
    ("00918", "大華優利高填息30"),
    ("0052", "富邦科技"),
    ("00878", "國泰永續高股息"),
    ("00953B", "群益優選非投等債"),
    ("00908", "國泰數位支付"),
]

# 5 年窗口排除 (2023 才上市)
TOP5YR_EXCLUDE = {"00939", "00953B"}  # 7 檔剩下

# 兩個窗口
WINDOWS = {
    "3yr": {
        "start": "2023-08-29",
        "end": "2026-08-29",
        "stocks": TOP9_UNION,  # 9 檔
        "label": "3 年窗口 (2023-08-29 ~ 2026-08-29)",
    },
    "5yr": {
        "start": "2021-08-29",
        "end": "2026-08-29",
        "stocks": [t for t in TOP9_UNION if t[0] not in TOP5YR_EXCLUDE],  # 7 檔
        "label": "5 年窗口 (2021-08-29 ~ 2026-08-29)",
    },
}

# 蒙地卡羅參數
N_COMBOS_TARGET = 5000
SEED = 42
DIRICHLET_ALPHA = 2.0
MIN_STOCKS = 5
MAX_STOCKS = 10
MAX_SINGLE_WEIGHT = 0.35  # 主人指示


def log(msg):
    ts = time.strftime("%H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line, flush=True)
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(line + "\n")


# ============================================================
# Step A: 重抓 9 檔 union 從上市日起 (yfinance auto_adjust)
# ============================================================
def fetch_full_history():
    """重抓 9 檔從上市日 (period=max) 到 2026-08-29"""
    log("=" * 70)
    log("📈 Step A: 重抓 9 檔 union 從上市日起 (yfinance auto_adjust)")
    log("=" * 70)

    cache_path = CACHE_DIR / "full_history.parquet"
    if cache_path.exists():
        log(f"  使用 cache: {cache_path}")
        return pd.read_parquet(cache_path)

    prices = {}
    for tid, name in TOP9_UNION:
        for sfx in [".TW", ".TWO"]:  # 主 + 備援
            try:
                t = yf.Ticker(f"{tid}{sfx}")
                h = t.history(period="max", auto_adjust=True)
                if h is not None and len(h) >= 252:
                    s = h["Close"].dropna()
                    s.index = pd.to_datetime(s.index).tz_localize(None) if hasattr(s.index, 'tz') and s.index.tz is not None else s.index
                    # 只取到 2026-08-29
                    s = s[s.index <= pd.Timestamp("2026-08-29")]
                    if len(s) >= 252:
                        prices[tid] = s
                        log(f"  ✅ {tid} ({name}) [{sfx}]: "
                            f"{s.index[0].date()} ~ {s.index[-1].date()} ({len(s)} days)")
                        break
            except Exception as e:
                log(f"  ⚠️ {tid} ({sfx}): {e}")

    if not prices:
        raise RuntimeError("完全抓不到資料")

    # 對齊 common index (但每檔各自的歷史起點不同)
    # 不取 common — 保留每檔各自的歷史
    # 但輸出時只取到 2026-08-29
    df = pd.DataFrame(prices)

    # 對齊：先 forward-fill，再取到 2026-08-29
    df = df.ffill().dropna(how="all")

    # 儲存
    df.to_parquet(cache_path)
    log(f"  💾 Cached: {cache_path} ({df.shape})")

    return df


# ============================================================
# Step B: 對齊窗口 + 計算單檔 metrics
# ============================================================
def compute_metrics_from_prices(prices_s, rf=RF):
    """從單檔價格序列算 6 分數（與 v1 同公式）"""
    s = prices_s.dropna()
    if len(s) < 252:
        return None
    if isinstance(s, pd.DataFrame):
        s = s.iloc[:, 0]

    total_return = float(s.iloc[-1] / s.iloc[0] - 1)
    years = (s.index[-1] - s.index[0]).days / 365.25
    if years <= 0:
        return None
    cagr = float((1 + total_return) ** (1 / years) - 1)
    daily_ret = s.pct_change().dropna()
    vol = float(daily_ret.std() * np.sqrt(252))
    sharpe = float((cagr - rf) / vol) if vol > 0 else -999.0
    downside = daily_ret[daily_ret < 0]
    if len(downside) > 1:
        dvol = float(downside.std() * np.sqrt(252))
        sortino = float((cagr - rf) / dvol) if dvol > 0 else -999.0
    else:
        sortino = 99.0
    peak = s.cummax()
    dd = s / peak - 1
    mdd = float(dd.min())
    calmar = float(cagr / abs(mdd)) if mdd != 0 else 0.0

    return {
        "total_return": total_return,
        "cagr": cagr,
        "vol": vol,
        "sharpe": sharpe,
        "sortino": sortino,
        "mdd": mdd,
        "calmar": calmar,
        "n_years": years,
        "n_days": len(s),
    }


def align_window(prices_df, window_key):
    """對齊單一窗口：取 window 內資料；對每檔用 max(window_start, listing_date)

    重要：common index 從「最晚 eff_start」開始，這樣所有 stock 都有完整數據。
    但 CAGR/Calmar 仍用每檔自己 eff_start 算年化，保留「中途進場」語意。
    """
    cfg = WINDOWS[window_key]
    start = pd.Timestamp(cfg["start"])
    end = pd.Timestamp(cfg["end"])
    stock_list = cfg["stocks"]

    log(f"\n🪟 對齊 {window_key} 窗口: {start.date()} ~ {end.date()} ({len(stock_list)} 檔)")

    # 先取每檔的窗口資料（各自 eff_start）
    sub_prices = {}      # 完整 eff_start 起的 series
    eff_starts = {}      # 每檔的有效起點
    for tid, name in stock_list:
        if tid not in prices_df.columns:
            log(f"  ⚠️ {tid} 不在 cache 中")
            continue
        s = prices_df[tid].dropna()
        eff_start = max(start, s.index[0])
        s = s[(s.index >= eff_start) & (s.index <= end)]
        if len(s) < 252:
            log(f"  ⚠️ {tid}: 窗口內只有 {len(s)} 天 (< 252), 跳過")
            continue
        sub_prices[tid] = s
        eff_starts[tid] = eff_start
        log(f"  ✅ {tid} ({name}): eff_start={eff_start.date()} "
            f"~ {s.index[-1].date()} ({len(s)} days, {len(s)/252:.2f}y)")

    if len(sub_prices) < MIN_STOCKS:
        raise RuntimeError(f"{window_key} 窗口少於 {MIN_STOCKS} 檔")

    # 對齊 common index：從「最晚 eff_start」開始 (這樣全部 stock 都有資料)
    common_start = max(eff_starts.values())
    aligned = pd.DataFrame({
        tid: s[s.index >= common_start] for tid, s in sub_prices.items()
    })
    # 內部仍有 NaN 跳過（理論上從 common_start 起不該有）
    aligned = aligned.dropna(axis=1, how="any")
    log(f"  Common date range: {aligned.index[0].date()} ~ {aligned.index[-1].date()} "
        f"({len(aligned)} trading days, eff_start={common_start.date()})")

    # 計算每檔 metrics（用各檔 eff_start 算年化, 不一律用 common_start）
    stock_metrics = {}
    for tid in aligned.columns:
        s = sub_prices[tid]  # ⭐ 用各檔 eff_start 起的完整 series
        m = compute_metrics_from_prices(s)
        if m:
            stock_metrics[tid] = m

    # 計算 returns matrix
    returns = aligned.pct_change().dropna(how="all").dropna(axis=1, how="any")

    return aligned, returns, stock_metrics


# ============================================================
# Step C: 蒙地卡羅生組合
# ============================================================
def generate_combos(stock_tids, n_target=N_COMBOS_TARGET, seed=SEED):
    """蒙地卡羅: Dirichlet α=2, 5-10 檔, 單檔 ≤ 35%
    MAX_STOCKS 自動 cap 在可用 stock 數"""
    # Cap max at available count
    max_n = min(MAX_STOCKS, len(stock_tids))
    min_n = min(MIN_STOCKS, max_n)
    log(f"\n🎲 蒙地卡羅生 {n_target} 組合 (α={DIRICHLET_ALPHA}, "
        f"{min_n}-{max_n} 檔 [cap by universe {len(stock_tids)}], "
        f"max_w ≤ {MAX_SINGLE_WEIGHT:.0%})")

    rng = np.random.default_rng(seed)
    combos = []

    n_attempts = 0
    while len(combos) < n_target and n_attempts < n_target * 5:
        n_stocks = int(rng.integers(min_n, max_n + 1))
        tids = rng.choice(stock_tids, size=n_stocks, replace=False).tolist()
        weights = rng.dirichlet([DIRICHLET_ALPHA] * n_stocks)
        # 過濾
        if max(weights) > MAX_SINGLE_WEIGHT:
            n_attempts += 1
            continue
        combos.append({"tids": tids, "weights": weights.tolist()})
        n_attempts += 1

    log(f"  ✅ 生成 {len(combos)} 組合（嘗試 {n_attempts} 次）")
    return combos


# ============================================================
# Step D: 計算組合 metrics
# ============================================================
def compute_combo_metrics(returns_df, combo_tids, combo_weights):
    """計算單一組合 6 分數"""
    try:
        sub = returns_df[combo_tids].dropna()
        if len(sub) < 252:
            return None
        w = np.array(combo_weights)
        if len(w) != len(combo_tids):
            return None
        port_ret = pd.Series(sub.values @ w, index=sub.index)
        cum = (1 + port_ret).cumprod()
        total_return = float(cum.iloc[-1] - 1)
        years = (cum.index[-1] - cum.index[0]).days / 365.25
        if years <= 0:
            return None
        cagr = float((1 + total_return) ** (1 / years) - 1)
        vol = float(port_ret.std() * np.sqrt(252))
        sharpe = float((cagr - RF) / vol) if vol > 0 else -999.0
        downside = port_ret[port_ret < 0]
        if len(downside) > 1:
            dvol = float(downside.std() * np.sqrt(252))
            sortino = float((cagr - RF) / dvol) if dvol > 0 else -999.0
        else:
            sortino = 99.0
        peak = cum.cummax()
        dd = cum / peak - 1
        mdd = float(dd.min())
        calmar = float(cagr / abs(mdd)) if mdd != 0 else 0.0
        return {
            "total_return": total_return, "cagr": cagr, "vol": vol,
            "sharpe": sharpe, "sortino": sortino, "mdd": mdd, "calmar": calmar,
            "n_years": years, "n_days": len(sub),
        }
    except Exception as e:
        return None


def score_combinations(combos, returns_df, log_every=500):
    """對所有組合算 metrics + 排名 + 總分"""
    log(f"\n📊 計算 {len(combos)} 組合的 6 分數")

    rows = []
    n_done = 0
    n_fail = 0
    t0 = time.time()
    for i, c in enumerate(combos):
        if i % log_every == 0 and i > 0:
            elapsed = time.time() - t0
            rate = i / elapsed if elapsed > 0 else 0
            eta = (len(combos) - i) / rate if rate > 0 else 0
            log(f"  ⏳ {i}/{len(combos)} — {n_done} ok, {n_fail} fail — "
                f"{elapsed:.1f}s elapsed, ETA {eta:.0f}s")
        m = compute_combo_metrics(returns_df, c["tids"], c["weights"])
        if m is None:
            n_fail += 1
            continue
        rows.append({
            "combo_id": i,
            "n_stocks": len(c["tids"]),
            "tids": "|".join(c["tids"]),
            "weights": "|".join([f"{w:.4f}" for w in c["weights"]]),
            **m,
        })
        n_done += 1
    log(f"  ✅ Computed {n_done}/{len(combos)} ({n_fail} fail), time {time.time()-t0:.1f}s")

    df = pd.DataFrame(rows)

    # 排名
    df["rank_total_return"] = df["total_return"].rank(ascending=False, method="min")
    df["rank_cagr"] = df["cagr"].rank(ascending=False, method="min")
    df["rank_sharpe"] = df["sharpe"].rank(ascending=False, method="min")
    df["rank_sortino"] = df["sortino"].rank(ascending=False, method="min")
    df["rank_mdd"] = df["mdd"].rank(ascending=True, method="min")  # 越接近 0 越好
    df["rank_calmar"] = df["calmar"].rank(ascending=False, method="min")

    rank_cols = ["rank_total_return", "rank_cagr", "rank_sharpe",
                 "rank_sortino", "rank_mdd", "rank_calmar"]
    df["total_score"] = df[rank_cols].sum(axis=1)
    df["overall_rank"] = df["total_score"].rank(method="min")

    log(f"  6 分數分布：")
    for col in ["total_return", "cagr", "sharpe", "sortino", "mdd", "calmar"]:
        s = df[col]
        log(f"    {col:15s} median={s.median():>9.4f}  mean={s.mean():>9.4f}  "
            f"max={s.max():>9.4f}  min={s.min():>9.4f}")

    return df


# ============================================================
# Step E: 寫出單一窗口結果
# ============================================================
def write_window_results(window_key, df_ranked, returns_df, stock_metrics, stock_list):
    cfg = WINDOWS[window_key]
    out_csv = OUT_DIR / f"phase3_v2_{window_key}_combinations.csv"
    out_md = OUT_DIR / f"phase3_v2_{window_key}_top3.md"

    out_cols = [
        "combo_id", "n_stocks", "tids", "weights",
        "total_return", "cagr", "vol", "sharpe", "sortino", "mdd", "calmar",
        "n_years", "n_days",
        "rank_total_return", "rank_cagr", "rank_sharpe",
        "rank_sortino", "rank_mdd", "rank_calmar",
        "total_score", "overall_rank",
    ]
    df_ranked[out_cols].to_csv(out_csv, index=False, encoding="utf-8-sig")
    log(f"  💾 {out_csv} ({len(df_ranked)} rows)")

    # MD 報告
    top3 = df_ranked.sort_values("overall_rank").head(3).reset_index(drop=True)
    medals = ["🥇", "🥈", "🥉"]

    md = []
    md.append(f"# 🏆 fund-plan Phase 3 v2 — {cfg['label']} Top 3\n")
    md.append(f"**生成時間**: {time.strftime('%Y-%m-%d %H:%M:%S')}  ")
    md.append(f"**適用股號**: {len(stock_list)} 檔  ")
    md.append(f"**候選組合**: {len(df_ranked)} (蒙地卡羅 {N_COMBOS_TARGET} 目標)  ")
    md.append(f"**算法**: Dirichlet α={DIRICHLET_ALPHA}, {MIN_STOCKS}-{MAX_STOCKS} 檔, "
              f"單檔 ≤ {MAX_SINGLE_WEIGHT:.0%} + 6 分數排名（總分低 = 好）\n")
    md.append("---\n")

    name_map = dict(TOP9_UNION)

    for idx, row in top3.iterrows():
        medal = medals[idx]
        md.append(f"## {medal} #{idx+1} 組合（總分 {int(row['total_score'])}）\n")
        tids = row["tids"].split("|")
        weights = [float(w) for w in row["weights"].split("|")]

        md.append("### 成份股與權重\n")
        md.append("| ETF | 名稱 | 權重 | CAGR | Sharpe | MDD |")
        md.append("|---|---|---:|---:|---:|---:|")
        for tid, w in zip(tids, weights):
            name = name_map.get(tid, "?")
            m = stock_metrics.get(tid, {})
            md.append(f"| {tid} | {name} | {w:.1%} | "
                      f"{m.get('cagr', 0):.1%} | {m.get('sharpe', 0):.2f} | "
                      f"{m.get('mdd', 0):.1%} |")

        md.append("\n### 組合指標\n")
        md.append("| 指標 | 數值 | 排名 |")
        md.append("|---|---:|---:|")
        md.append(f"| 總報酬 | {row['total_return']:.2%} | #{int(row['rank_total_return'])} |")
        md.append(f"| CAGR | {row['cagr']:.2%} | #{int(row['rank_cagr'])} |")
        md.append(f"| Sharpe | {row['sharpe']:.3f} | #{int(row['rank_sharpe'])} |")
        md.append(f"| Sortino | {row['sortino']:.3f} | #{int(row['rank_sortino'])} |")
        md.append(f"| MDD | {row['mdd']:.2%} | #{int(row['rank_mdd'])} |")
        md.append(f"| Calmar | {row['calmar']:.3f} | #{int(row['rank_calmar'])} |")
        md.append(f"| **總分** | **{int(row['total_score'])}** | **#{int(row['overall_rank'])}** |")
        md.append("")

        md.append("### 為何選這個？\n")
        n_total = len(df_ranked)
        for metric, rcol in [
            ("Sharpe", "rank_sharpe"), ("CAGR", "rank_cagr"), ("Sortino", "rank_sortino"),
            ("MDD", "rank_mdd"), ("Calmar", "rank_calmar"), ("總報酬", "rank_total_return"),
        ]:
            rk = int(row[rcol])
            pct = rk / n_total * 100
            md.append(f"- {metric} 排名全市場前 {pct:.1f}% (#{rk})")
        md.append("\n---\n")

    # Top 20 表
    md.append("\n## 📋 Top 20 速覽\n")
    md.append("| Rank | Stocks | CAGR | Sharpe | Sortino | MDD | Calmar | Total Ret | 總分 |")
    md.append("|---:|---:|---:|---:|---:|---:|---:|---:|---:|")
    top20 = df_ranked.sort_values("overall_rank").head(20)
    for _, row in top20.iterrows():
        md.append(f"| #{int(row['overall_rank'])} | {row['n_stocks']} | "
                  f"{row['cagr']:.2%} | {row['sharpe']:.2f} | {row['sortino']:.2f} | "
                  f"{row['mdd']:.2%} | {row['calmar']:.2f} | {row['total_return']:.2%} | "
                  f"{int(row['total_score'])} |")

    md.append("\n## 📊 6 分數分布\n")
    md.append("| 指標 | 中位 | 平均 | 最大 | 最小 |")
    md.append("|---|---:|---:|---:|---:|")
    for col in ["total_return", "cagr", "sharpe", "sortino", "mdd", "calmar"]:
        s = df_ranked[col]
        md.append(f"| {col} | {s.median():.4f} | {s.mean():.4f} | {s.max():.4f} | {s.min():.4f} |")

    out_md.write_text("\n".join(md), encoding="utf-8")
    log(f"  💾 {out_md}")

    return top3


# ============================================================
# Main
# ============================================================
def main():
    log("=" * 70)
    log("🚀 fund-plan Phase 3 v2 — 加長回測期（3 年 + 5 年）")
    log("=" * 70)
    t_start = time.time()

    # Step A: 重抓 9 檔 union 從上市日起
    prices_df = fetch_full_history()

    # Step B + C + D + E: 對每個窗口
    results = {}
    for wkey in ["3yr", "5yr"]:
        log(f"\n{'='*70}\n📐 處理 {wkey} 窗口\n{'='*70}")
        aligned, returns, stock_metrics = align_window(prices_df, wkey)

        # 蒙地卡羅
        stock_tids = list(stock_metrics.keys())
        combos = generate_combos(stock_tids)

        # 計分
        df_ranked = score_combinations(combos, returns)

        # 寫出
        stock_list = WINDOWS[wkey]["stocks"]
        top3 = write_window_results(wkey, df_ranked, returns, stock_metrics, stock_list)

        results[wkey] = {
            "df": df_ranked,
            "stock_metrics": stock_metrics,
            "top3": top3,
            "aligned": aligned,
            "returns": returns,
        }

    # ===== 跨窗口比較 =====
    log(f"\n{'='*70}\n🔍 跨窗口比較 (3yr vs 5yr)\n{'='*70}")

    # 儲存對齊後資料供 phase4 使用
    for wkey in ["3yr", "5yr"]:
        aligned = results[wkey]["aligned"]
        ret = results[wkey]["returns"]
        aligned.to_parquet(CACHE_DIR / f"{wkey}_aligned.parquet")
        ret.to_parquet(CACHE_DIR / f"{wkey}_returns.parquet")
        log(f"  💾 {wkey}: aligned ({aligned.shape}) + returns ({ret.shape})")

    # Top 3 重疊度
    top3_3yr_tids = set()
    for _, row in results["3yr"]["top3"].iterrows():
        top3_3yr_tids.update(row["tids"].split("|"))
    top3_5yr_tids = set()
    for _, row in results["5yr"]["top3"].iterrows():
        top3_5yr_tids.update(row["tids"].split("|"))

    log(f"  Top 3 union (3yr): {sorted(top3_3yr_tids)}")
    log(f"  Top 3 union (5yr): {sorted(top3_5yr_tids)}")
    log(f"  重疊: {sorted(top3_3yr_tids & top3_5yr_tids)}")

    # 寫 JSON
    summary = {
        "phase": "3-v2",
        "date": time.strftime("%Y-%m-%d %H:%M:%S"),
        "owner_directive": "#5082 + #5085: 加長回測期 (3y + 5y) + 半年再平衡 + 交易成本 + bear + walk-forward",
        "windows": {},
    }
    for wkey in ["3yr", "5yr"]:
        cfg = WINDOWS[wkey]
        df = results[wkey]["df"]
        sm = results[wkey]["stock_metrics"]
        top3 = results[wkey]["top3"]
        aligned = results[wkey]["aligned"]
        ret = results[wkey]["returns"]

        top3_data = []
        for idx, row in top3.iterrows():
            tids = row["tids"].split("|")
            weights = [float(w) for w in row["weights"].split("|")]
            comp = []
            for tid, w in zip(tids, weights):
                name = dict(TOP9_UNION).get(tid, "?")
                m = sm.get(tid, {})
                comp.append({
                    "tid": tid, "name": name, "weight": round(w, 4),
                    "cagr": round(m.get("cagr", 0), 4),
                    "sharpe": round(m.get("sharpe", 0), 4),
                    "mdd": round(m.get("mdd", 0), 4),
                })
            top3_data.append({
                "rank": int(row["overall_rank"]),
                "total_score": int(row["total_score"]),
                "metrics": {
                    "total_return": round(float(row["total_return"]), 4),
                    "cagr": round(float(row["cagr"]), 4),
                    "sharpe": round(float(row["sharpe"]), 4),
                    "sortino": round(float(row["sortino"]), 4),
                    "mdd": round(float(row["mdd"]), 4),
                    "calmar": round(float(row["calmar"]), 4),
                },
                "components": comp,
            })

        summary["windows"][wkey] = {
            "label": cfg["label"],
            "date_range": [
                str(aligned.index[0].date()),
                str(aligned.index[-1].date()),
            ],
            "n_trading_days": int(len(ret)),
            "n_stocks": int(len(aligned.columns)),
            "n_combos": int(len(df)),
            "top_3": top3_data,
        }

    summary["overlap"] = {
        "top3_union_3yr": sorted(top3_3yr_tids),
        "top3_union_5yr": sorted(top3_5yr_tids),
        "common_tids": sorted(top3_3yr_tids & top3_5yr_tids),
    }

    summary["phase3_elapsed_seconds"] = round(time.time() - t_start, 1)
    SUMMARY_FILE.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    log(f"\n💾 {SUMMARY_FILE}")

    log(f"\n✅ Phase 3 v2 完成 — {time.time()-t_start:.1f}s")
    log("=" * 70)


if __name__ == "__main__":
    main()
