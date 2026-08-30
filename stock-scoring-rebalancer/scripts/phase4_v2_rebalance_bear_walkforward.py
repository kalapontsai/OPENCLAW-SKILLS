#!/usr/bin/env python3
"""
fund-plan Phase 4 v2 — 半年再平衡 + 交易成本 + bear + walk-forward

主人 #5085 指示：
- 半年再平衡（每年 2 次：2月第 1 個交易日 + 8月第 1 個交易日）
- 交易成本：0.1425% × 2 (買 + 賣) = 0.285% per round-trip, 0.57% 年化
- bear scenario：找所有 10 個月窗口中累計報酬最低者（用 9 檔 union full history）
- walk-forward：3yr (2y in + 1y out) + 5yr (3y in + 2y out)

四個模組輸出：
1. 半年再平衡 vs buy-hold 比較
2. Bear scenario (Top 3 在最壞 10 個月表現)
3. Walk-forward (in-sample vs out-of-sample 重疊度)
4. 結構化 JSON 結論
"""
from __future__ import annotations
import sys, json, time
from pathlib import Path
import numpy as np
import pandas as pd
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

LOG_FILE = LOG_DIR / "phase3_v2_phase4_v2.log"
SUMMARY_FILE = LOG_DIR / "phase3v2_phase4v2_summary.json"

# ===== 參數（主人 #5085 指定）=====
ROUND_TRIP_COST = 0.00285  # 0.1425% × 2
ANNUALIZED_COST = ROUND_TRIP_COST * 2  # 0.57% (每年 2 次再平衡)
RF = 0.02

# 9 檔 union
TOP9 = ["00881", "00935", "00690", "00939", "00918", "0052", "00878", "00953B", "00908"]


def log(msg):
    ts = time.strftime("%H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line, flush=True)
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def calc_metrics_from_returns(port_ret, rf=RF):
    """從 port return series 算 6 分數"""
    if port_ret is None or len(port_ret) < 30:
        return None
    cum = (1 + port_ret).cumprod()
    total_return = float(cum.iloc[-1] - 1)
    years = (cum.index[-1] - cum.index[0]).days / 365.25
    if years <= 0:
        return None
    cagr = float((1 + total_return) ** (1 / years) - 1)
    vol = float(port_ret.std() * np.sqrt(252))
    sharpe = float((cagr - rf) / vol) if vol > 0 else -999.0
    downside = port_ret[port_ret < 0]
    sortino = float((cagr - rf) / (downside.std() * np.sqrt(252))) \
        if len(downside) > 1 else 99.0
    peak = cum.cummax()
    dd = cum / peak - 1
    mdd = float(dd.min())
    calmar = float(cagr / abs(mdd)) if mdd != 0 else 0.0
    return {
        "total_return": total_return, "cagr": cagr, "vol": vol,
        "sharpe": sharpe, "sortino": sortino, "mdd": mdd, "calmar": calmar,
        "n_years": years, "n_days": len(port_ret),
    }


# ============================================================
# 半年再平衡引擎
# ============================================================
def get_rebalance_dates(returns_df, start_year, end_year):
    """每年 2 月第 1 個交易日 + 8 月第 1 個交易日"""
    reb_dates = []
    for year in range(start_year, end_year + 1):
        for month in [2, 8]:
            mask = (returns_df.index.year == year) & (returns_df.index.month == month)
            if mask.any():
                first = returns_df.index[mask][0]
                reb_dates.append(first)
    return sorted(set(reb_dates))


def simulate_rebalance(returns_df, tids, target_weights, cost=ROUND_TRIP_COST,
                       rebalance=True):
    """模擬 buy-and-hold 或 半年再平衡

    Args:
        returns_df: daily returns matrix (columns = tickers)
        tids: 組合成份股
        target_weights: 目標權重（list, sum=1）
        cost: round-trip cost (default 0.285%)
        rebalance: 是否再平衡

    Returns:
        (port_ret_series, rebalance_events: list of {date, turnover, cost})
    """
    target_w = np.array(target_weights)
    sub = returns_df[tids].dropna()
    if len(sub) < 30:
        return None, []

    if not rebalance:
        # buy-and-hold: 直接按初始權重計算每日收益
        port_ret = sub.values @ target_w
        port_ret = pd.Series(port_ret, index=sub.index)
        return port_ret, []

    # Re-balance mode: 追蹤 current_w drift
    current_w = target_w.copy()
    port_ret = []
    events = []

    reb_date_set = set(get_rebalance_dates(sub, sub.index[0].year, sub.index[-1].year))

    last_date = None
    for date in sub.index:
        if last_date is None:
            port_ret.append(0.0)
        else:
            r = sub.loc[date].values
            r = np.nan_to_num(r, nan=0.0)
            day_ret = float(current_w @ r)
            port_ret.append(day_ret)
            # 更新 current_w（隱含再投資）
            current_w = current_w * (1 + r)
            if current_w.sum() > 0:
                current_w = current_w / current_w.sum()

        # 檢查是否需要 rebalance
        if date in reb_date_set:
            turnover = float(np.sum(np.abs(current_w - target_w)) / 2)
            tx_cost = turnover * cost
            port_ret[-1] -= tx_cost
            events.append({
                "date": str(date.date()),
                "turnover": round(turnover, 4),
                "cost": round(tx_cost, 6),
                "pre_drift_max": round(float(np.max(np.abs(current_w - target_w))), 4),
            })
            current_w = target_w.copy()

        last_date = date

    port_ret_series = pd.Series(port_ret, index=sub.index)
    return port_ret_series, events


# ============================================================
# Bear scenario engine
# ============================================================
def find_bear_window(returns_df, tids, window_months=10, top_n=3):
    """在歷史中找累計報酬最低的 10 個月窗口

    回傳 top_n 個最差窗口（用於 sensitivity）
    """
    sub = returns_df[tids].dropna()
    if len(sub) < 60:
        return []

    # 等權重組合找最差窗口
    eq_w = np.ones(len(tids)) / len(tids)
    port = sub.values @ eq_w
    port = pd.Series(port, index=sub.index)

    win_days = 21 * window_months  # 10 個月 = ~210 交易日

    cum = (1 + port).cumprod()
    rolling_ret = cum / cum.shift(win_days) - 1
    rolling_ret = rolling_ret.dropna()

    sorted_idx = rolling_ret.sort_values().index
    bears = []
    for idx in sorted_idx[:top_n]:
        end_pos = sub.index.get_loc(idx)
        start_pos = max(0, end_pos - win_days + 1)
        start_date = sub.index[start_pos]
        end_date = idx
        window_ret = float(rolling_ret.loc[idx])
        window_slice = cum.loc[start_date:end_date]
        peak = window_slice.cummax()
        dd = window_slice / peak - 1
        window_mdd = float(dd.min())
        bears.append({
            "start_date": str(start_date.date()),
            "end_date": str(end_date.date()),
            "cumulative_return": round(window_ret, 4),
            "mdd": round(window_mdd, 4),
            "n_days": end_pos - start_pos + 1,
            "n_months": round((end_pos - start_pos + 1) / 21, 1),
        })
    return bears


def evaluate_in_bear(returns_df, tids, weights, bear_window):
    """計算組合在 bear window 內的表現"""
    start = pd.Timestamp(bear_window["start_date"])
    end = pd.Timestamp(bear_window["end_date"])
    sub = returns_df[tids].loc[start:end].dropna()
    if len(sub) < 10:
        return {"total_return": None, "mdd": None, "n_days": 0}
    w = np.array(weights)
    port = pd.Series(sub.values @ w, index=sub.index)
    cum = (1 + port).cumprod()
    total_ret = float(cum.iloc[-1] - 1)
    peak = cum.cummax()
    dd = cum / peak - 1
    mdd = float(dd.min())
    return {
        "total_return": round(total_ret, 4),
        "mdd": round(mdd, 4),
        "n_days": len(sub),
    }


# ============================================================
# Walk-forward engine
# ============================================================
def _combo_metrics(returns_df, tids, weights, rf=RF):
    """Walk-forward 內部用"""
    try:
        sub = returns_df[tids].dropna()
        if len(sub) < 30:
            return None
        w = np.array(weights)
        port_ret = pd.Series(sub.values @ w, index=sub.index)
        cum = (1 + port_ret).cumprod()
        total_return = float(cum.iloc[-1] - 1)
        years = (cum.index[-1] - cum.index[0]).days / 365.25
        if years <= 0:
            return None
        cagr = float((1 + total_return) ** (1 / years) - 1)
        vol = float(port_ret.std() * np.sqrt(252))
        sharpe = float((cagr - rf) / vol) if vol > 0 else -999.0
        downside = port_ret[port_ret < 0]
        sortino = float((cagr - rf) / (downside.std() * np.sqrt(252))) \
            if len(downside) > 1 else 99.0
        peak = cum.cummax()
        dd = cum / peak - 1
        mdd = float(dd.min())
        calmar = float(cagr / abs(mdd)) if mdd != 0 else 0.0
        return {
            "total_return": total_return, "cagr": cagr, "vol": vol,
            "sharpe": sharpe, "sortino": sortino, "mdd": mdd, "calmar": calmar,
            "n_years": years, "n_days": len(sub),
        }
    except Exception:
        return None


def run_walkforward(returns_df, stock_tids, split_date, n_target=5000, seed=42):
    """對一個 split 點, 跑 in-sample + out-of-sample"""
    in_data = returns_df[returns_df.index < split_date].dropna()
    out_data = returns_df[returns_df.index >= split_date].dropna()

    if len(in_data) < 60 or len(out_data) < 30:
        log(f"    ⚠️ 資料不足: in={len(in_data)}, out={len(out_data)} (跳過)")
        return None

    log(f"    in-sample: {in_data.index[0].date()} ~ {in_data.index[-1].date()} ({len(in_data)}d)")
    log(f"    out-of-sample: {out_data.index[0].date()} ~ {out_data.index[-1].date()} ({len(out_data)}d)")

    # 共用同一組蒙地卡羅 combos (保證 in/out 評比公平)
    rng = np.random.default_rng(seed)
    combos = []
    n_attempts = 0
    n_max = min(9, len(stock_tids))
    n_min = min(5, n_max)

    while len(combos) < n_target and n_attempts < n_target * 5:
        n_stocks = int(rng.integers(n_min, n_max + 1))
        tids = rng.choice(stock_tids, size=n_stocks, replace=False).tolist()
        weights = rng.dirichlet([2.0] * n_stocks)
        if max(weights) > 0.35:
            n_attempts += 1
            continue
        combos.append({"tids": tids, "weights": weights.tolist()})
        n_attempts += 1

    def _score(data):
        rows = []
        for c in combos:
            m = _combo_metrics(data, c["tids"], c["weights"])
            if m is None:
                continue
            rows.append({"tids": c["tids"], "weights": c["weights"], **m})
        if not rows:
            return None, []
        df = pd.DataFrame(rows)
        df["total_score"] = (
            df["total_return"].rank(ascending=False) +
            df["cagr"].rank(ascending=False) +
            df["sharpe"].rank(ascending=False) +
            df["sortino"].rank(ascending=False) +
            df["mdd"].rank(ascending=True) +
            df["calmar"].rank(ascending=False)
        )
        df["overall_rank"] = df["total_score"].rank(method="min")
        return df.sort_values("overall_rank"), df

    in_top, in_df = _score(in_data)
    out_top, out_df = _score(out_data)
    if in_top is None or out_top is None:
        return None

    in_top3 = in_top.head(3)
    out_top3 = out_top.head(3)

    in_top3_tids = set()
    for _, row in in_top3.iterrows():
        in_top3_tids.update(row["tids"])
    out_top3_tids = set()
    for _, row in out_top3.iterrows():
        out_top3_tids.update(row["tids"])

    overlap = in_top3_tids & out_top3_tids
    union = in_top3_tids | out_top3_tids
    overlap_pct = len(overlap) / len(union) if union else 0

    in_combo_keys = set(tuple(sorted(r["tids"])) for _, r in in_top3.iterrows())
    out_combo_keys = set(tuple(sorted(r["tids"])) for _, r in out_top3.iterrows())
    exact_overlap = in_combo_keys & out_combo_keys
    exact_pct = len(exact_overlap) / 3.0

    log(f"    In-sample Top 3 stocks: {sorted(in_top3_tids)}")
    log(f"    Out-of-sample Top 3 stocks: {sorted(out_top3_tids)}")
    log(f"    重疊度 (stock-level): {overlap_pct:.1%} ({len(overlap)}/{len(union)})")
    log(f"    重疊度 (combo-level): {exact_pct:.1%} ({len(exact_overlap)}/3)")

    return {
        "in_sample": {
            "date_range": [str(in_data.index[0].date()), str(in_data.index[-1].date())],
            "n_days": int(len(in_data)),
            "n_combos": int(len(in_df)),
            "top3_stocks": sorted(in_top3_tids),
            "top3_combos": [
                {"tids": row["tids"], "cagr": round(row["cagr"], 4),
                 "sharpe": round(row["sharpe"], 4), "mdd": round(row["mdd"], 4)}
                for _, row in in_top3.iterrows()
            ],
        },
        "out_of_sample": {
            "date_range": [str(out_data.index[0].date()), str(out_data.index[-1].date())],
            "n_days": int(len(out_data)),
            "n_combos": int(len(out_df)),
            "top3_stocks": sorted(out_top3_tids),
            "top3_combos": [
                {"tids": row["tids"], "cagr": round(row["cagr"], 4),
                 "sharpe": round(row["sharpe"], 4), "mdd": round(row["mdd"], 4)}
                for _, row in out_top3.iterrows()
            ],
        },
        "overlap": {
            "stock_level_pct": round(overlap_pct * 100, 1),
            "combo_level_pct": round(exact_pct * 100, 1),
            "common_stocks": sorted(overlap),
            "verdict": "穩健" if overlap_pct >= 0.6 else ("過擬合" if overlap_pct < 0.3 else "中性"),
        },
    }


# ============================================================
# Main
# ============================================================
def main():
    log("=" * 70)
    log("🚀 fund-plan Phase 4 v2 — 半年再平衡 + 交易成本 + bear + walk-forward")
    log("=" * 70)
    t_start = time.time()

    # Load aligned data per window (從 phase3 v2 寫的 parquet)
    log("\n📦 載入 phase3v2 對齊後資料...")
    window_data = {}
    for wkey in ["3yr", "5yr"]:
        aligned_path = CACHE_DIR / f"{wkey}_aligned.parquet"
        returns_path = CACHE_DIR / f"{wkey}_returns.parquet"
        if not aligned_path.exists():
            log(f"  ❌ 找不到 {aligned_path}, 請先跑 phase3_v2")
            sys.exit(1)
        aligned = pd.read_parquet(aligned_path)
        returns = pd.read_parquet(returns_path)
        window_data[wkey] = {
            "aligned": aligned,
            "returns": returns,
        }
        log(f"  {wkey}: aligned {aligned.shape}, returns {returns.shape}, "
            f"{aligned.index[0].date()} ~ {aligned.index[-1].date()}")

    # 讀 phase3 v2 結果
    log("\n📋 讀 Phase 3 v2 Top 3...")
    top3_by_window = {}
    for wkey in ["3yr", "5yr"]:
        df = pd.read_csv(OUT_DIR / f"phase3_v2_{wkey}_combinations.csv")
        top3 = df.sort_values("overall_rank").head(3).reset_index(drop=True)
        top3_by_window[wkey] = top3
        all_tids = sorted(set("|".join(top3["tids"].tolist()).split("|")))
        log(f"  {wkey}: Top 3 stocks = {all_tids}")

    # ===== 1. 半年再平衡 vs buy-hold =====
    log("\n" + "=" * 70)
    log("🔄 模組 1: 半年再平衡 vs buy-and-hold")
    log("=" * 70)

    rebalance_results = []
    for wkey in ["3yr", "5yr"]:
        log(f"\n📐 {wkey} 窗口")
        returns_df = window_data[wkey]["returns"]

        for rank_idx, row in top3_by_window[wkey].iterrows():
            tids = row["tids"].split("|")
            weights = [float(w) for w in row["weights"].split("|")]
            log(f"\n  Top {rank_idx+1}: {tids}")

            bh_ret, _ = simulate_rebalance(returns_df, tids, weights, rebalance=False)
            bh_metrics = calc_metrics_from_returns(bh_ret)

            rb_ret, events = simulate_rebalance(returns_df, tids, weights, rebalance=True)
            rb_metrics = calc_metrics_from_returns(rb_ret)

            total_cost = sum(e["cost"] for e in events)
            cost_pct = total_cost / bh_metrics["total_return"] if bh_metrics["total_return"] > 0 else 0

            log(f"    buy-hold:  CAGR={bh_metrics['cagr']:.2%}, "
                f"Sharpe={bh_metrics['sharpe']:.3f}, MDD={bh_metrics['mdd']:.2%}")
            log(f"    rebalance: CAGR={rb_metrics['cagr']:.2%}, "
                f"Sharpe={rb_metrics['sharpe']:.3f}, MDD={rb_metrics['mdd']:.2%}")
            log(f"    rebalance 次數: {len(events)}, 累計成本: {total_cost:.4f} "
                f"({cost_pct:.2%} of return)")

            rebalance_results.append({
                "window": wkey,
                "rank": rank_idx + 1,
                "tids": "|".join(tids),
                "weights": "|".join([f"{w:.4f}" for w in weights]),
                "buy_hold_cagr": round(bh_metrics["cagr"], 4),
                "buy_hold_sharpe": round(bh_metrics["sharpe"], 4),
                "buy_hold_mdd": round(bh_metrics["mdd"], 4),
                "rebalance_cagr": round(rb_metrics["cagr"], 4),
                "rebalance_sharpe": round(rb_metrics["sharpe"], 4),
                "rebalance_mdd": round(rb_metrics["mdd"], 4),
                "n_rebalances": len(events),
                "total_turnover_cost": round(total_cost, 6),
                "cost_pct_of_return": round(cost_pct, 4),
                "cagr_diff": round(rb_metrics["cagr"] - bh_metrics["cagr"], 4),
            })

    rb_df = pd.DataFrame(rebalance_results)
    rb_df.to_csv(OUT_DIR / "phase4_v2_rebalance_compare.csv", index=False, encoding="utf-8-sig")
    log(f"\n💾 {OUT_DIR / 'phase4_v2_rebalance_compare.csv'}")

    # ===== 2. Bear scenario =====
    log("\n" + "=" * 70)
    log("🐻 模組 2: Bear scenario (10 個月滑動窗口找最差)")
    log("=" * 70)

    bear_results = []
    # 用 9 檔 union 完整歷史（從 phase3v2 cache 的 prices）
    log("\n📦 載入 9 檔 union full history (從 phase3v2 cache)...")
    full_prices = pd.read_parquet(CACHE_DIR / "full_history.parquet")
    full_returns = full_prices.pct_change().dropna(how="all")
    log(f"  Full returns: {full_returns.shape}, "
        f"{full_returns.index[0].date()} ~ {full_returns.index[-1].date()}")

    # 9 檔 union 對齊到 common (從最晚 listing 日期起)
    common_full = full_returns[TOP9].dropna()
    log(f"  9 檔 union common: {common_full.shape}, "
        f"{common_full.index[0].date()} ~ {common_full.index[-1].date()}")

    # 找最差 10 個月窗口（取前 3 個最差）
    bears = find_bear_window(common_full, TOP9, window_months=10, top_n=3)
    if not bears:
        log("  ⚠️ 找不到 bear window")
    else:
        log(f"\n  📉 最差 10 個月窗口（用等權重 9 檔 union）:")
        for i, b in enumerate(bears):
            log(f"    #{i+1}: {b['start_date']} ~ {b['end_date']} "
                f"cum_ret={b['cumulative_return']:.2%}, MDD={b['mdd']:.2%}, "
                f"({b['n_days']}d, {b['n_months']}mo)")

        worst_bear = bears[0]

        # 對每個窗口的 Top 3 評估（在 worst bear window 內）
        for wkey in ["3yr", "5yr"]:
            log(f"\n📐 {wkey} 窗口 Top 3 在 worst bear 表現")
            for rank_idx, row in top3_by_window[wkey].iterrows():
                tids = row["tids"].split("|")
                weights = [float(w) for w in row["weights"].split("|")]
                perf = evaluate_in_bear(common_full, tids, weights, worst_bear)
                log(f"  Top {rank_idx+1} ({tids}): "
                    f"cum_ret={perf['total_return']}, MDD={perf['mdd']}")

                bear_results.append({
                    "window": wkey,
                    "rank": rank_idx + 1,
                    "tids": "|".join(tids),
                    "weights": "|".join([f"{w:.4f}" for w in weights]),
                    "bear_window_start": worst_bear["start_date"],
                    "bear_window_end": worst_bear["end_date"],
                    "bear_window_n_months": worst_bear["n_months"],
                    "bear_window_return_eq": worst_bear["cumulative_return"],
                    "bear_window_mdd_eq": worst_bear["mdd"],
                    "top_in_bear_return": perf["total_return"],
                    "top_in_bear_mdd": perf["mdd"],
                    "n_days": perf["n_days"],
                })

        # 也存 sensitivity（top 3 個最差窗口）的等權重結果
        sensitivity_df = pd.DataFrame(bears)
        sensitivity_df.to_csv(OUT_DIR / "phase4_v2_bear_sensitivity.csv",
                              index=False, encoding="utf-8-sig")
        log(f"\n💾 {OUT_DIR / 'phase4_v2_bear_sensitivity.csv'} (top-3 最差窗口)")

    bear_df = pd.DataFrame(bear_results)
    bear_df.to_csv(OUT_DIR / "phase4_v2_bear_scenario.csv", index=False, encoding="utf-8-sig")
    log(f"💾 {OUT_DIR / 'phase4_v2_bear_scenario.csv'}")

    # ===== 3. Walk-forward =====
    log("\n" + "=" * 70)
    log("⏩ 模組 3: Walk-forward (in-sample vs out-of-sample)")
    log("=" * 70)

    wf_results = {}
    for wkey in ["3yr", "5yr"]:
        log(f"\n📐 {wkey} 窗口")
        aligned = window_data[wkey]["aligned"]
        # 9 檔 union 但 5yr 只用 7 檔 (對齊後 columns 就是 5yr 適用的 7 檔)
        avail = aligned.columns.tolist()
        log(f"  Available stocks in window: {avail}")

        # 對齊到該窗口 stock 集合的 returns
        returns_df = window_data[wkey]["returns"]

        # split 日期
        if wkey == "3yr":
            # 2y in + 1y out (window 2024-08-12 ~ 2026-08-27, split ~2025-08-12)
            split_date = aligned.index[0] + (aligned.index[-1] - aligned.index[0]) * 2 // 3
        else:  # 5yr
            # 3y in + 2y out (window 2023-10-23 ~ 2026-08-27, split ~2025-04-23)
            split_date = aligned.index[0] + (aligned.index[-1] - aligned.index[0]) * 3 // 5

        log(f"  Split date: {split_date.date()}")
        result = run_walkforward(returns_df, avail, split_date)
        if result:
            wf_results[wkey] = result

    wf_rows = []
    for wkey, r in wf_results.items():
        in_top = r["in_sample"]["top3_stocks"]
        out_top = r["out_of_sample"]["top3_stocks"]
        wf_rows.append({
            "window": wkey,
            "in_period": f"{r['in_sample']['date_range'][0]} ~ {r['in_sample']['date_range'][1]}",
            "out_period": f"{r['out_of_sample']['date_range'][0]} ~ {r['out_of_sample']['date_range'][1]}",
            "in_top3_stocks": "|".join(in_top),
            "out_top3_stocks": "|".join(out_top),
            "stock_overlap_pct": r["overlap"]["stock_level_pct"],
            "combo_overlap_pct": r["overlap"]["combo_level_pct"],
            "common_stocks": "|".join(r["overlap"]["common_stocks"]),
            "verdict": r["overlap"]["verdict"],
        })
    wf_df = pd.DataFrame(wf_rows)
    wf_df.to_csv(OUT_DIR / "phase4_v2_walkforward.csv", index=False, encoding="utf-8-sig")
    log(f"\n💾 {OUT_DIR / 'phase4_v2_walkforward.csv'}")

    # ===== 4. Summary JSON =====
    log("\n" + "=" * 70)
    log("📋 模組 4: 結構化 JSON 結論")
    log("=" * 70)

    # 載入現有 summary (phase3 v2 已寫過)
    if SUMMARY_FILE.exists():
        existing = json.loads(SUMMARY_FILE.read_text(encoding="utf-8"))
    else:
        existing = {}

    existing["phase4_v2"] = {
        "transaction_cost_model": {
            "round_trip": f"{ROUND_TRIP_COST*100:.3f}%",
            "annualized": f"{ANNUALIZED_COST*100:.3f}%",
            "frequency": "半年一次 (Feb + Aug 第 1 個交易日)",
        },
        "rebalance_compare": rebalance_results,
        "bear_scenario": bear_results,
        "walk_forward": {
            wkey: {
                "in_period": r["in_sample"]["date_range"],
                "out_period": r["out_of_sample"]["date_range"],
                "in_top3": r["in_sample"]["top3_stocks"],
                "out_top3": r["out_of_sample"]["top3_stocks"],
                "overlap_pct": r["overlap"]["stock_level_pct"],
                "combo_overlap_pct": r["overlap"]["combo_level_pct"],
                "verdict": r["overlap"]["verdict"],
            }
            for wkey, r in wf_results.items()
        },
    }

    SUMMARY_FILE.write_text(json.dumps(existing, ensure_ascii=False, indent=2), encoding="utf-8")
    log(f"💾 {SUMMARY_FILE}")

    log(f"\n✅ Phase 4 v2 完成 — {time.time()-t_start:.1f}s")


if __name__ == "__main__":
    main()
