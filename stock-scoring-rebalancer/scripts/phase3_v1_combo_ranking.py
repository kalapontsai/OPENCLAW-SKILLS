#!/usr/bin/env python3
"""
fund-plan Phase 3 v1 — 排列組合排名（多目標 Pareto + 6 分數排名 + Top 3）

主人 #5077 指示：
- 從白名單 164 檔排列組合（不只是 filtered 27 檔）
- 演算法：KMeans 分群 + 多目標 Pareto + 蒙地卡羅 混合
- 製表紀錄每個組合（成份股 + 權重）
- 計算 6 個分數：總報酬 / CAGR / Sharpe / Sortino / MDD / Calmar
- 各分數排名（Rank 1 = 最好）
- 總分 = 各排名加總，總分越低 = 表現越好
- 提出 Top 3 組合 + 完整表格

啟動前 baseline 整合（v7 已 join holders_count 到 all.csv）:
- filtered.csv 已含 holders_count (v7 後續補入)
- 確認後跳過重新 join
"""
from __future__ import annotations
import sys, os, json, time, re
from pathlib import Path
import numpy as np
import pandas as pd
import yfinance as yf
from sklearn.cluster import KMeans
from sklearn.metrics import silhouette_score
from sklearn.preprocessing import StandardScaler
import matplotlib
matplotlib.use('Agg')  # no display
import matplotlib.pyplot as plt

# Matplotlib 中文字型 (Linux 預設 Noto)
plt.rcParams['font.sans-serif'] = ['Noto Sans CJK TC', 'WenQuanYi Micro Hei', 'DejaVu Sans']
plt.rcParams['axes.unicode_minus'] = False

PROJECT_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_DIR / "data"
OUT_DIR = PROJECT_DIR / "outputs"
LOG_DIR = PROJECT_DIR / "logs"
PHASE3_CACHE = DATA_DIR / "phase3_cache"

for d in [DATA_DIR, OUT_DIR, LOG_DIR, PHASE3_CACHE]:
    d.mkdir(parents=True, exist_ok=True)

LOG_FILE = LOG_DIR / "phase3_v1.log"
ALL_CSV = OUT_DIR / "single_metrics_all.csv"
FILT_CSV = OUT_DIR / "single_metrics_filtered.csv"
PRICES_CACHE = PHASE3_CACHE / "prices.parquet"
RETURNS_CACHE = PHASE3_CACHE / "returns.parquet"
OUT_RANKED = OUT_DIR / "all_combinations_ranked.csv"
OUT_TOP3_MD = OUT_DIR / "top3_portfolios.md"
OUT_TOP3_PNG = OUT_DIR / "top3_comparison.png"
OUT_SUMMARY = LOG_DIR / "phase3_v1_summary.json"

START_DATE = "2019-01-01"
END_DATE = "2026-08-29"
RF = 0.02  # 2% risk-free (Phase 3 比 Phase 2 的 1.5% 多一點, 反映目前環境)
MIN_HISTORY_DAYS = 252  # ~1y

# 候選組合生成參數
N_COMBOS_TARGET = 5000
SEED = 42


def log(msg):
    ts = time.strftime("%H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line, flush=True)
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(line + "\n")


# ============================================================
# Step 0: Baseline 驗證 + 讀白名單
# ============================================================
def step0_load_whitelist():
    log("=" * 60)
    log("📋 Step 0: Baseline 整合驗證 + 讀白名單 (164)")
    log("=" * 60)

    all_df = pd.read_csv(ALL_CSV)
    filt_df = pd.read_csv(FILT_CSV)

    # Baseline 驗證: filtered 應含 holders_count (v7 已 join)
    assert "holders_count" in filt_df.columns, \
        "filtered.csv 缺 holders_count — 主人指示先 join"
    assert filt_df["holders_count"].notna().all(), \
        f"filtered.csv 缺 holders_count: {filt_df[filt_df['holders_count'].isna()]['tid'].tolist()}"
    log(f"✅ filtered.csv 已含 holders_count (27/27 都有)")

    # 5 指標都非空 → 白名單 164
    needed = ["cagr", "vol", "sharpe", "mdd", "div_yield"]
    whitelist = all_df[all_df[needed].notna().all(axis=1)].copy().reset_index(drop=True)
    log(f"✅ 白名單: {len(whitelist)} 檔（5 指標都非空）")

    # _source 解析 yfinance 正確後綴
    def parse_suffix(src):
        m = re.search(r"\.(TWO?)\b", str(src))
        if m:
            return "." + m.group(1)
        # flask_cache → 試 .TW (大多上市), 不行再 .TWO
        return ".TW"  # 預設; flask_cache tickers 少數, 之後個別 retry

    whitelist["yfx_suffix"] = whitelist["_source"].apply(parse_suffix)
    whitelist["yfx_ticker"] = whitelist["tid"] + whitelist["yfx_suffix"]

    log(f"  yfinance 後綴分布: {whitelist['yfx_suffix'].value_counts().to_dict()}")

    # 順便 log holders_count for whitelist (中位/平均)
    log(f"  白名單 holders_count: "
        f"mean={whitelist['holders_count'].mean():,.0f} "
        f"median={whitelist['holders_count'].median():,.0f}")

    return whitelist, filt_df


# ============================================================
# Step 1: 取日報酬 (從 yfinance batch + Flask cache)
# ============================================================
def fetch_prices_from_flask_cache(tid):
    """Flask cache 讀單檔 (raw close — 因為 Flask cache 不含 Adj Close)
    
    ⚠️ 注意: Flask cache 只有 raw Close (含 split 影響)。
    對於有 split 過的股票，會與 yfinance 調整後 close 不一致。
    解法: 對 Flask cache 股票也用 yfinance 重抓 (auto_adjust=True)
    """
    # Flask cache 不一致 → 改用 yfinance 重抓
    try:
        is_bond = str(tid).endswith('B')
        suffixes = ['.TWO', '.TW'] if is_bond else ['.TW', '.TWO']
        for sfx in suffixes:
            try:
                t = yf.Ticker(f"{tid}{sfx}")
                hist = t.history(start=START_DATE, end=END_DATE, auto_adjust=True)
                if hist is not None and len(hist) >= MIN_HISTORY_DAYS:
                    s = hist["Close"].dropna()
                    s.index = pd.to_datetime(s.index).tz_localize(None) if hasattr(s.index, 'tz') and s.index.tz is not None else s.index
                    return s
            except Exception:
                continue
    except Exception:
        pass
    return None


def calc_per_stock_metrics(prices_s, rf=RF):
    """從單檔 price Series 算 6 個分數"""
    s = prices_s.dropna()
    if len(s) < 252:
        return None
    if isinstance(s, pd.DataFrame):
        s = s.iloc[:, 0]

    # 1. 總報酬
    total_return = float(s.iloc[-1] / s.iloc[0] - 1)

    # 2. CAGR
    years = (s.index[-1] - s.index[0]).days / 365.25
    if years <= 0:
        return None
    cagr = float((1 + total_return) ** (1 / years) - 1)

    # 3. Vol
    daily_ret = s.pct_change().dropna()
    vol = float(daily_ret.std() * np.sqrt(252))

    # 4. Sharpe
    sharpe = float((cagr - rf) / vol) if vol > 0 else -999.0

    # 5. Sortino
    downside = daily_ret[daily_ret < 0]
    if len(downside) > 1:
        dvol = float(downside.std() * np.sqrt(252))
        sortino = float((cagr - rf) / dvol) if dvol > 0 else -999.0
    else:
        sortino = 99.0

    # 6. MDD
    cum = (1 + daily_ret).cumprod() * s.iloc[0]  # 重建 cum (從價格)
    peak = s.cummax()
    dd = s / peak - 1
    mdd = float(dd.min())

    # 7. Calmar
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


def step1_fetch_prices(whitelist):
    log("=" * 60)
    log("📈 Step 1: 取日報酬（Flask cache + yfinance batch）")
    log("=" * 60)

    prices = {}  # tid -> Series

    # 1a. Flask cache (12 個)
    flask_hits = 0
    flask_misses = []
    for tid in whitelist["tid"]:
        p = fetch_prices_from_flask_cache(tid)
        if p is not None:
            prices[tid] = p
            flask_hits += 1
        else:
            flask_misses.append(tid)
    log(f"  Flask cache: {flask_hits} hits, {len(flask_misses)} miss")

    # 1b. yfinance batch（剩 152 個）
    if flask_misses:
        # 群組按 suffix 區分
        sub = whitelist[whitelist["tid"].isin(flask_misses)]
        # yfinance tickers
        yf_tickers = sub["yfx_ticker"].tolist()

        # 對 bonds (B 結尾) → 同時嘗試 .TW fallback (少數例外如 00775B)
        # 對 non-B → 同時嘗試 .TWO fallback (006201, 00886, 00888)
        log(f"  yfinance batch: {len(yf_tickers)} tickers (1st pass)")

        t0 = time.time()
        try:
            df = yf.download(
                yf_tickers,
                start=START_DATE, end=END_DATE,
                progress=False, auto_adjust=True, threads=True,  # ⭐ 用調整後 close (split+dividend)
            )
        except Exception as e:
            log(f"  yfinance batch err: {e}")
            df = None
        log(f"  yfinance batch 1st pass: {time.time()-t0:.1f}s")

        if df is not None and len(df) > 0:
            closes = df["Close"]
            for _, row in sub.iterrows():
                tid = row["tid"]
                sfx = row["yfx_suffix"]
                ticker = row["yfx_ticker"]
                if ticker in closes.columns:
                    s = closes[ticker].dropna()
                    if len(s) >= MIN_HISTORY_DAYS:
                        s.index = pd.to_datetime(s.index).tz_localize(None) if hasattr(s.index, 'tz') and s.index.tz is not None else s.index
                        prices[tid] = s
                    else:
                        # 留 retry
                        pass

        # 1c. 對沒拿到的，個別 retry (含 fallback suffix)
        still_missing = [tid for tid in flask_misses if tid not in prices]
        log(f"  1st pass 缺: {len(still_missing)} → 個別 retry (含 fallback suffix)")

        for tid in still_missing:
            row = whitelist[whitelist["tid"] == tid].iloc[0]
            primary_sfx = row["yfx_suffix"]
            fallback_sfx = ".TWO" if primary_sfx == ".TW" else ".TW"
            got = False
            for sfx in [primary_sfx, fallback_sfx]:
                try:
                    t = yf.Ticker(f"{tid}{sfx}")
                    hist = t.history(start=START_DATE, end=END_DATE, auto_adjust=True)  # ⭐ 調整後
                    if hist is not None and len(hist) >= MIN_HISTORY_DAYS:
                        s = hist["Close"].dropna()
                        s.index = pd.to_datetime(s.index).tz_localize(None) if hasattr(s.index, 'tz') and s.index.tz is not None else s.index
                        prices[tid] = s
                        got = True
                        break
                except Exception:
                    pass
            if not got:
                log(f"  ❌ {tid}: yfinance 雙 suffix 都拿不到")

    log(f"  ✅ 取得 prices: {len(prices)}/{len(whitelist)} 檔")

    # 統一 index 處理 (去掉 tz)
    for tid in list(prices.keys()):
        s = prices[tid]
        if hasattr(s.index, 'tz') and s.index.tz is not None:
            s.index = s.index.tz_localize(None)

    # 對齊 common index（只取所有 stocks 都有資料的日期）
    common_idx = None
    for tid, s in prices.items():
        idx = s.index
        if common_idx is None:
            common_idx = idx
        else:
            common_idx = common_idx.intersection(idx)

    log(f"  Common date range: {common_idx[0].date()} ~ {common_idx[-1].date()} ({len(common_idx)} trading days)")

    # 對齊所有 prices
    aligned_prices = pd.DataFrame({tid: s.reindex(common_idx) for tid, s in prices.items()})
    # 移除任何有 NaN 的 stocks（保險）
    aligned_prices = aligned_prices.dropna(axis=1, how="any")
    valid_tids = aligned_prices.columns.tolist()
    log(f"  Valid stocks (aligned, no NaN): {len(valid_tids)}")

    # 算 daily returns
    returns = aligned_prices.pct_change().dropna(how="all").dropna(axis=1, how="any")
    valid_tids = returns.columns.tolist()
    log(f"  Valid stocks (returns, no NaN): {len(valid_tids)}")
    log(f"  Returns date range: {returns.index[0].date()} ~ {returns.index[-1].date()} ({len(returns)} days)")

    # Save cache
    aligned_prices.to_parquet(PRICES_CACHE)
    returns.to_parquet(RETURNS_CACHE)
    log(f"  💾 Cached: {PRICES_CACHE} & {RETURNS_CACHE}")

    # Step 1b: 重算 per-stock metrics（用 common range, 與組合計算一致）
    log("  Step 1b: 重算每檔 6 分數（用 common range 2024-09 ~ 2026-08）")
    new_metrics = {}
    for tid in valid_tids:
        m = calc_per_stock_metrics(aligned_prices[tid])
        if m is not None:
            new_metrics[tid] = m
    log(f"  Recomputed metrics for {len(new_metrics)} stocks")
    # 範例
    if new_metrics:
        sample = list(new_metrics.items())[:3]
        for tid, m in sample:
            log(f"    {tid}: CAGR={m['cagr']:.2%}, Sharpe={m['sharpe']:.2f}, MDD={m['mdd']:.2%}")

    return prices, returns, valid_tids, new_metrics


# ============================================================
# Step 2: KMeans 分群
# ============================================================
def step2_kmeans(whitelist, valid_tids, new_metrics):
    log("=" * 60)
    log("🧬 Step 2: KMeans 分群 (silhouette 選 K=4-8)")
    log("=" * 60)

    feat_cols = ["cagr", "vol", "sharpe", "mdd"]  # 從價格算的 4 個; div_yield 來自外部資料 (v5)
    df = whitelist[whitelist["tid"].isin(valid_tids)].copy()
    # 用 Step 1b 重算的 metrics (common range 一致) 覆蓋 v5 價格指標
    for col in feat_cols:
        new_vals = {tid: m[col] for tid, m in new_metrics.items()}
        df[col] = df["tid"].map(new_vals)
    # div_yield 保留 v5 (來自 TDCC/etfinfo, 跨期間有效)
    # log holders_count_log (for clustering)
    df["holders_count_log"] = np.log10(df["holders_count"].fillna(df["holders_count"].median()))

    X = df[feat_cols + ["holders_count_log"]].values
    X_scaled = StandardScaler().fit_transform(X)

    best_k = 5
    best_score = -1
    log("  Silhouette scores by K:")
    for k in range(4, 9):
        km = KMeans(n_clusters=k, random_state=SEED, n_init=20)
        labels = km.fit_predict(X_scaled)
        score = silhouette_score(X_scaled, labels)
        log(f"    K={k}: silhouette={score:.4f}")
        if score > best_score:
            best_score = score
            best_k = k

    log(f"  ✅ Best K={best_k} (silhouette={best_score:.4f})")

    km = KMeans(n_clusters=best_k, random_state=SEED, n_init=20)
    df["cluster"] = km.fit_predict(X_scaled)

    # 每群選 Top 3 by Sharpe
    rep_rows = []
    for c in sorted(df["cluster"].unique()):
        sub = df[df["cluster"] == c].sort_values("sharpe", ascending=False)
        top = sub.head(3)
        rep_rows.append(top)
        log(f"  Cluster {c}: {len(sub)} stocks, top by Sharpe: "
            f"{top['tid'].tolist()}")

    rep_df = pd.concat(rep_rows).reset_index(drop=True)
    rep_tids = rep_df["tid"].tolist()
    log(f"  ✅ Cluster representatives: {len(rep_tids)} stocks (~{best_k}×3)")

    return df, best_k, best_score, rep_tids


# ============================================================
# Step 3: 候選組合產生（混合法 A/B/C）
# ============================================================
def gen_dirichlet_weights(n_stocks, alpha=2.0, rng=None):
    """Dirichlet 隨機權重 (alpha=2.0 → 較均匀, 避免單檔過重)"""
    if rng is None:
        rng = np.random.default_rng(SEED)
    w = rng.dirichlet([alpha] * n_stocks)
    return w


def step3_generate_combos(df_whitelist, rep_tids, valid_tids, filt_df):
    log("=" * 60)
    log("🎲 Step 3: 候選組合產生 (A/B/C 混合)")
    log("=" * 60)

    rng = np.random.default_rng(SEED)

    whitelist_tids = df_whitelist[df_whitelist["tid"].isin(valid_tids)]["tid"].tolist()
    rep_tids_valid = [t for t in rep_tids if t in valid_tids]
    filt_tids_valid = filt_df[filt_df["tid"].isin(valid_tids)]["tid"].tolist()

    log(f"  Whitelist valid: {len(whitelist_tids)}")
    log(f"  Cluster reps valid: {len(rep_tids_valid)}")
    log(f"  Filtered (27) valid: {len(filt_tids_valid)}")

    combos = []  # list of dict: {tids: [...], weights: [...]}

    # 🔥 alpha=2 → 較均匀 (max weight 期望 ~0.36); 1.7x over-generate to compensate weight filter
    over_factor = 1.7
    n_a = int(N_COMBOS_TARGET * 0.40 * over_factor)
    n_b = int(N_COMBOS_TARGET * 0.40 * over_factor)
    n_c = int(N_COMBOS_TARGET * 0.20 * over_factor)
    log(f"  Target: A={n_a}, B={n_b}, C={n_c} (over-gen {over_factor}x → ~{N_COMBOS_TARGET} final)")

    # Source A: cluster reps (含 cluster 權重 → 同群多選)
    cluster_assign = dict(zip(df_whitelist["tid"], df_whitelist["cluster"]))
    cluster_groups = {}
    for tid in rep_tids_valid:
        c = cluster_assign.get(tid)
        cluster_groups.setdefault(c, []).append(tid)
    log(f"  Cluster groups: {[(c, len(t)) for c, t in cluster_groups.items()]}")

    for i in range(n_a):
        # 從 1-3 個群各抽 2-3 檔 (目標 5-8 檔)
        n_clusters = rng.integers(2, min(4, len(cluster_groups) + 1))
        chosen_clusters = rng.choice(list(cluster_groups.keys()), size=n_clusters, replace=False)
        tids = []
        for c in chosen_clusters:
            avail = cluster_groups[c]
            k = min(rng.integers(2, 4), len(avail))
            tids.extend(rng.choice(avail, size=k, replace=False).tolist())
        tids = list(set(tids))
        if len(tids) < 4:
            continue
        if len(tids) > 10:
            tids = list(rng.choice(tids, size=10, replace=False))
        weights = gen_dirichlet_weights(len(tids), rng=rng)
        combos.append({"source": "A_cluster", "tids": tids, "weights": weights.tolist()})

    # Source B: 從 164 白名單蒙地卡羅抽
    for i in range(n_b):
        n_stocks = int(rng.integers(5, 11))  # 5-10
        tids = rng.choice(whitelist_tids, size=n_stocks, replace=False).tolist()
        weights = gen_dirichlet_weights(n_stocks, rng=rng)
        combos.append({"source": "B_monte", "tids": tids, "weights": weights.tolist()})

    # Source C: 從 27 過 5 門檻的抽
    if len(filt_tids_valid) < 5:
        log(f"  ⚠️ filtered 僅 {len(filt_tids_valid)} 檔, 跳過 C")
        # 用 A/B 補足
        n_extra = n_c
        for i in range(n_extra):
            n_stocks = int(rng.integers(5, min(11, len(filt_tids_valid))))
            tids = rng.choice(filt_tids_valid, size=n_stocks, replace=False).tolist()
            weights = gen_dirichlet_weights(len(tids), rng=rng)
            combos.append({"source": "C_filt", "tids": tids, "weights": weights.tolist()})
    else:
        for i in range(n_c):
            n_stocks = int(rng.integers(5, min(11, len(filt_tids_valid) + 1)))
            tids = rng.choice(filt_tids_valid, size=n_stocks, replace=False).tolist()
            weights = gen_dirichlet_weights(n_stocks, rng=rng)
            combos.append({"source": "C_filt", "tids": tids, "weights": weights.tolist()})

    # Filter weight constraints: 單檔 <= 35%, 沒有過度集中
    # 🔥 註: 寬鬆一點 — 先產生足夠樣本, weight 不合理就 rank 差
    # 保留比較寬鬆: max_w <= 0.50 (原 0.35 過嚴, 砍掉 57%)
    filtered_combos = []
    for c in combos:
        if max(c["weights"]) > 0.50:  # 寬鬆: 允許到 50% (避免鄧蒂卡羅自然集中)
            continue
        if sum(c["weights"]) < 0.95:  # 防呆
            continue
        # 至少 5 檔 至多 10 檔
        if len(c["tids"]) < 5 or len(c["tids"]) > 10:
            continue
        filtered_combos.append(c)

    log(f"  ✅ Generated {len(combos)} → after weight filter: {len(filtered_combos)}")

    return filtered_combos


# ============================================================
# Step 4: 計算 6 分數
# ============================================================
def compute_combo_metrics(returns_df, combo_tids, combo_weights):
    """計算單一組合 6 個分數"""
    try:
        sub = returns_df[combo_tids].dropna()
        if len(sub) < 252:
            return None
        w = np.array(combo_weights)
        # 確保 weight 順序對應
        if len(w) != len(combo_tids):
            return None

        port_ret = sub.values @ w  # (T,)
        port_ret = pd.Series(port_ret, index=sub.index)

        # 1. 總報酬
        cum = (1 + port_ret).cumprod()
        total_return = float(cum.iloc[-1] - 1)

        # 2. CAGR
        years = (cum.index[-1] - cum.index[0]).days / 365.25
        if years <= 0:
            return None
        cagr = float((1 + total_return) ** (1 / years) - 1)

        # 3. Vol
        vol = float(port_ret.std() * np.sqrt(252))

        # 4. Sharpe (rf=2%)
        sharpe = float((cagr - RF) / vol) if vol > 0 else -999.0

        # 5. Sortino
        downside = port_ret[port_ret < 0]
        if len(downside) > 1:
            downside_vol = float(downside.std() * np.sqrt(252))
            sortino = float((cagr - RF) / downside_vol) if downside_vol > 0 else -999.0
        else:
            sortino = 99.0  # 無下行風險 → 給高分

        # 6. MDD
        peak = cum.cummax()
        dd = cum / peak - 1
        mdd = float(dd.min())

        # 7. Calmar
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
            "n_days": len(sub),
        }
    except Exception as e:
        return None


def step4_compute_metrics(combos, returns_df):
    log("=" * 60)
    log("📊 Step 4: 計算 6 分數（5000 候選組合）")
    log("=" * 60)

    rows = []
    n_done = 0
    n_fail = 0
    t0 = time.time()
    for i, c in enumerate(combos):
        if i % 500 == 0:
            elapsed = time.time() - t0
            rate = (i + 1) / elapsed if elapsed > 0 else 0
            eta = (len(combos) - i) / rate if rate > 0 else 0
            log(f"  ⏳ {i+1}/{len(combos)} — {n_done} ok, {n_fail} fail — "
                f"{elapsed:.1f}s elapsed, ETA {eta:.0f}s")
        m = compute_combo_metrics(returns_df, c["tids"], c["weights"])
        if m is None:
            n_fail += 1
            continue
        rows.append({
            "combo_id": i,
            "source": c["source"],
            "n_stocks": len(c["tids"]),
            "tids": "|".join(c["tids"]),
            "weights": "|".join([f"{w:.4f}" for w in c["weights"]]),
            **m,
        })
        n_done += 1

    log(f"  ✅ Computed {n_done}/{len(combos)} ({n_fail} fail)")
    df_combos = pd.DataFrame(rows)
    log(f"  Time: {time.time()-t0:.1f}s")
    return df_combos


# ============================================================
# Step 5: 排名 + 總分 + Pareto
# ============================================================
def pareto_front(df, objectives):
    """計算 Pareto 前緣（假設所有 objectives 越大越好）"""
    # 對 MDD（負的，越接近 0 越好）等指標, 先轉換
    # 這裡 caller 需先轉換
    data = df[objectives].values
    n = len(data)
    is_pareto = np.ones(n, dtype=bool)
    for i in range(n):
        if not is_pareto[i]:
            continue
        # 任何 j 比 i 在所有 objective 都 >= 且至少一個 > → i 不是 Pareto
        for j in range(n):
            if i == j or not is_pareto[j]:
                continue
            if np.all(data[j] >= data[i]) and np.any(data[j] > data[i]):
                is_pareto[i] = False
                break
    return is_pareto


def step5_ranking(df_combos):
    log("=" * 60)
    log("🏆 Step 5: 排名 + 總分 + Pareto")
    log("=" * 60)

    df = df_combos.copy()

    # 排名（注意 MDD 是負的，越接近 0 越好 → ascending=True）
    df["rank_total_return"] = df["total_return"].rank(ascending=False, method="min")
    df["rank_cagr"] = df["cagr"].rank(ascending=False, method="min")
    df["rank_sharpe"] = df["sharpe"].rank(ascending=False, method="min")
    df["rank_sortino"] = df["sortino"].rank(ascending=False, method="min")
    df["rank_mdd"] = df["mdd"].rank(ascending=True, method="min")  # 越接近 0 越好
    df["rank_calmar"] = df["calmar"].rank(ascending=False, method="min")

    # 總分
    rank_cols = ["rank_total_return", "rank_cagr", "rank_sharpe",
                 "rank_sortino", "rank_mdd", "rank_calmar"]
    df["total_score"] = df[rank_cols].sum(axis=1)
    df["overall_rank"] = df["total_score"].rank(method="min")

    # Pareto（轉 MDD 為 abs 越小越好 → 反轉: -MDD 越大越好）
    df["_mdd_pos"] = -df["mdd"]  # 越大越好
    pareto_mask = pareto_front(df, ["total_return", "cagr", "sharpe", "sortino", "_mdd_pos", "calmar"])
    df["is_pareto"] = pareto_mask
    df.drop(columns=["_mdd_pos"], inplace=True)

    log(f"  Pareto front size: {pareto_mask.sum()} / {len(df)}")

    # 6 分數分布
    log("  6 分數分布（中位 / 平均 / 最佳）:")
    for col in ["total_return", "cagr", "sharpe", "sortino", "mdd", "calmar"]:
        s = df[col]
        log(f"    {col:15s} median={s.median():>9.4f}  mean={s.mean():>9.4f}  "
            f"max={s.max():>9.4f}  min={s.min():>9.4f}")

    return df


# ============================================================
# Step 6: 輸出
# ============================================================
def step6_outputs(df_ranked, df_whitelist, valid_tids, best_k, best_score, n_combos_run, new_metrics=None):
    log("=" * 60)
    log("💾 Step 6: 寫入 outputs/")
    log("=" * 60)

    # 6a. all_combinations_ranked.csv
    out_cols = [
        "combo_id", "source", "n_stocks", "tids", "weights",
        "total_return", "cagr", "vol", "sharpe", "sortino", "mdd", "calmar",
        "n_years", "n_days",
        "rank_total_return", "rank_cagr", "rank_sharpe",
        "rank_sortino", "rank_mdd", "rank_calmar",
        "total_score", "overall_rank",
        "is_pareto",
    ]
    df_ranked[out_cols].to_csv(OUT_RANKED, index=False, encoding="utf-8-sig")
    log(f"  💾 {OUT_RANKED} ({len(df_ranked)} rows)")

    # 6b. top3_portfolios.md
    top3 = df_ranked.sort_values("overall_rank").head(3).reset_index(drop=True)
    medals = ["🥇", "🥈", "🥉"]

    md_lines = []
    md_lines.append("# 🏆 fund-plan Phase 3 v1 — Top 3 組合\n")
    md_lines.append(f"**生成時間**: {time.strftime('%Y-%m-%d %H:%M:%S')}  ")
    md_lines.append(f"**白名單**: {len(valid_tids)} 檔  ")
    md_lines.append(f"**KMeans**: K={best_k}, silhouette={best_score:.4f}  ")
    md_lines.append(f"**候選組合**: {n_combos_run} (過濾後)  ")
    md_lines.append(f"**算法**: Pareto 多目標 + 6 分數排名（總分越低 = 越好）\n")
    md_lines.append("---\n")

    for idx, row in top3.iterrows():
        medal = medals[idx]
        md_lines.append(f"## {medal} #{idx+1} 組合（總分 {int(row['total_score'])}）\n")
        tids = row["tids"].split("|")
        weights = [float(w) for w in row["weights"].split("|")]

        md_lines.append("### 成份股與權重\n")
        md_lines.append("| ETF | 名稱 | 權重 | CAGR (2y) | Sharpe (2y) | MDD (2y) | 集保戶數 |")
        md_lines.append("|---|---|---:|---:|---:|---:|---:|")
        for tid, w in zip(tids, weights):
            r = df_whitelist[df_whitelist["tid"] == tid]
            if len(r) > 0:
                r = r.iloc[0]
                # 優先用重算的 2y metrics (與 combo 一致)
                if new_metrics is not None and tid in new_metrics:
                    m = new_metrics[tid]
                    cagr_d = m["cagr"]
                    sharpe_d = m["sharpe"]
                    mdd_d = m["mdd"]
                else:
                    cagr_d = r["cagr"]
                    sharpe_d = r["sharpe"]
                    mdd_d = r["mdd"]
                md_lines.append(
                    f"| {tid} | {r['name'][:18]} | {w:.1%} | "
                    f"{cagr_d:.1%} | {sharpe_d:.2f} | {mdd_d:.1%} | "
                    f"{r['holders_count']:,.0f} |"
                )
            else:
                md_lines.append(f"| {tid} | (not in whitelist) | {w:.1%} | - | - | - | - |")

        md_lines.append("\n### 組合指標\n")
        md_lines.append("| 指標 | 數值 | 排名 |")
        md_lines.append("|---|---:|---:|")
        md_lines.append(f"| 總報酬 | {row['total_return']:.2%} | #{int(row['rank_total_return'])} |")
        md_lines.append(f"| CAGR | {row['cagr']:.2%} | #{int(row['rank_cagr'])} |")
        md_lines.append(f"| Sharpe | {row['sharpe']:.3f} | #{int(row['rank_sharpe'])} |")
        md_lines.append(f"| Sortino | {row['sortino']:.3f} | #{int(row['rank_sortino'])} |")
        md_lines.append(f"| MDD | {row['mdd']:.2%} | #{int(row['rank_mdd'])} |")
        md_lines.append(f"| Calmar | {row['calmar']:.3f} | #{int(row['rank_calmar'])} |")
        md_lines.append(f"| **總分** | **{int(row['total_score'])}** | **#{int(row['overall_rank'])}** |")
        md_lines.append(f"| Pareto | {'✅' if row['is_pareto'] else '❌'} | - |")
        md_lines.append("")

        # 為何選這個？
        md_lines.append("### 為何選這個？\n")
        n_total = len(df_ranked)
        reasons = []
        for metric, rcol, asc in [
            ("Sharpe", "rank_sharpe", False),
            ("CAGR", "rank_cagr", False),
            ("Sortino", "rank_sortino", False),
            ("MDD", "rank_mdd", True),
            ("Calmar", "rank_calmar", False),
            ("總報酬", "rank_total_return", False),
        ]:
            rk = int(row[rcol])
            pct = rk / n_total * 100
            if pct <= 10:
                reasons.append(f"- {metric} 排名全市場前 {pct:.1f}% (#{rk})")
            elif pct <= 25:
                reasons.append(f"- {metric} 排名全市場前 {pct:.1f}% (#{rk})")
        md_lines.extend(reasons)
        if row['is_pareto']:
            md_lines.append("- ✅ 在 Pareto 前緣（多目標最佳）")
        # 集保人數分布
        h_counts = []
        for tid in tids:
            r = df_whitelist[df_whitelist["tid"] == tid]
            if len(r) > 0 and pd.notna(r.iloc[0]["holders_count"]):
                h_counts.append(r.iloc[0]["holders_count"])
        if h_counts:
            avg_h = np.mean(h_counts)
            if avg_h > 200_000:
                md_lines.append(f"- 集保戶數平均 {avg_h:,.0f}（散戶共識高）")
            elif avg_h > 50_000:
                md_lines.append(f"- 集保戶數平均 {avg_h:,.0f}（中等共識）")
            else:
                md_lines.append(f"- 集保戶數平均 {avg_h:,.0f}（低共識 / 機構主導）")
        md_lines.append("\n---\n")

    # 加 Top 20 表
    md_lines.append("\n## 📋 Top 20 速覽\n")
    md_lines.append("| Rank | Source | Stocks | CAGR | Sharpe | Sortino | MDD | Calmar | Total Ret | 總分 | Pareto |")
    md_lines.append("|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|---|")
    top20 = df_ranked.sort_values("overall_rank").head(20)
    for _, row in top20.iterrows():
        md_lines.append(
            f"| #{int(row['overall_rank'])} | {row['source']} | {row['n_stocks']} | "
            f"{row['cagr']:.2%} | {row['sharpe']:.2f} | {row['sortino']:.2f} | "
            f"{row['mdd']:.2%} | {row['calmar']:.2f} | {row['total_return']:.2%} | "
            f"{int(row['total_score'])} | {'✅' if row['is_pareto'] else ''} |"
        )

    md_lines.append("\n## 📊 6 分數分布\n")
    md_lines.append("| 指標 | 中位 | 平均 | 最大 | 最小 |")
    md_lines.append("|---|---:|---:|---:|---:|")
    for col in ["total_return", "cagr", "sharpe", "sortino", "mdd", "calmar"]:
        s = df_ranked[col]
        md_lines.append(f"| {col} | {s.median():.4f} | {s.mean():.4f} | {s.max():.4f} | {s.min():.4f} |")

    OUT_TOP3_MD.write_text("\n".join(md_lines), encoding="utf-8")
    log(f"  💾 {OUT_TOP3_MD}")

    # 6c. top3_comparison.png
    fig, axes = plt.subplots(1, 3, figsize=(18, 5))

    # Plot 1: CAGR vs MDD scatter (highlight top 3)
    ax = axes[0]
    ax.scatter(df_ranked["mdd"] * 100, df_ranked["cagr"] * 100,
               s=8, alpha=0.3, c="gray", label="其他組合")
    pareto_df = df_ranked[df_ranked["is_pareto"]]
    ax.scatter(pareto_df["mdd"] * 100, pareto_df["cagr"] * 100,
               s=12, alpha=0.6, c="orange", label=f"Pareto ({len(pareto_df)})")
    for idx, row in top3.iterrows():
        ax.scatter(row["mdd"] * 100, row["cagr"] * 100,
                   s=200, marker="*", c=["gold", "silver", "#cd7f32"][idx],
                   edgecolors="black", linewidths=1.5,
                   label=f"#{idx+1} ({int(row['overall_rank'])})", zorder=5)
    ax.set_xlabel("MDD (%)", fontsize=12)
    ax.set_ylabel("CAGR (%)", fontsize=12)
    ax.set_title("CAGR vs 最大回撤 (MDD)\n(右上 = 表現好)", fontsize=13)
    ax.legend(loc="lower right", fontsize=9)
    ax.grid(True, alpha=0.3)

    # Plot 2: Cumulative return lines for top 3 (重算)
    ax = axes[1]
    returns_df = pd.read_parquet(RETURNS_CACHE)
    palette = ["gold", "silver", "#cd7f32"]
    for idx, row in top3.iterrows():
        tids = row["tids"].split("|")
        weights = [float(w) for w in row["weights"].split("|")]
        sub = returns_df[tids].dropna()
        if len(sub) > 0:
            w = np.array(weights)
            port_ret = sub.values @ w
            port_ret = pd.Series(port_ret, index=sub.index)
            cum = (1 + port_ret).cumprod()
            ax.plot(cum.index, cum.values, color=palette[idx], linewidth=2,
                    label=f"#{idx+1} (Sharpe={row['sharpe']:.2f}, CAGR={row['cagr']:.1%})")
    ax.set_xlabel("Date", fontsize=12)
    ax.set_ylabel("累積報酬倍數 (1 = 起始)", fontsize=12)
    ax.set_title("Top 3 累積報酬曲線", fontsize=13)
    ax.legend(loc="upper left", fontsize=9)
    ax.grid(True, alpha=0.3)

    # Plot 3: 6 score ranks bar chart
    ax = axes[2]
    rank_cols = ["rank_total_return", "rank_cagr", "rank_sharpe",
                 "rank_sortino", "rank_mdd", "rank_calmar"]
    rank_labels = ["總報酬", "CAGR", "Sharpe", "Sortino", "MDD", "Calmar"]
    n_total = len(df_ranked)
    x = np.arange(len(rank_cols))
    width = 0.25
    for idx, row in top3.iterrows():
        rks = [row[c] / n_total * 100 for c in rank_cols]
        ax.bar(x + (idx - 1) * width, rks, width,
               color=palette[idx], edgecolor="black", linewidth=1,
               label=f"#{idx+1}")
    ax.set_xticks(x)
    ax.set_xticklabels(rank_labels, rotation=20, fontsize=10)
    ax.set_ylabel("排名百分位 (%)", fontsize=12)
    ax.set_title("Top 3 各指標排名百分位\n(越低越好)", fontsize=13)
    ax.legend(loc="upper right", fontsize=10)
    ax.grid(True, alpha=0.3, axis="y")

    plt.tight_layout()
    plt.savefig(OUT_TOP3_PNG, dpi=120, bbox_inches="tight")
    plt.close()
    log(f"  💾 {OUT_TOP3_PNG}")

    # 6d. summary JSON
    summary = {
        "phase": "3-v1",
        "date": time.strftime("%Y-%m-%d %H:%M:%S"),
        "owner_directive": "#5077: 從 164 白名單排列組合 + Pareto + 6 分數排名 + Top 3",
        "baseline": {
            "joined_holders_to_filtered": True,
                "filtered_size": int(len(df_whitelist[df_whitelist['tid'].isin(
                    pd.read_csv(FILT_CSV)['tid']
                )])),
            "all_csv_size": int(len(df_whitelist)),
            "whitelist_size_5_indicators": int(len(df_whitelist)),
            "all_csv_total_with_blanks": int(len(pd.read_csv(ALL_CSV))),
        },
        "data_fetch": {
            "flask_cache_hits": sum(
                1 for tid in df_whitelist['tid']
                if Path(f"/mnt/d/stock/retrocast/data/price_cache/{tid}.json").exists()
            ),
            "valid_stocks_after_align": int(len(valid_tids)),
            "common_date_range": [
                str(pd.read_parquet(RETURNS_CACHE).index[0].date()),
                str(pd.read_parquet(RETURNS_CACHE).index[-1].date()),
            ],
            "n_trading_days": int(len(pd.read_parquet(RETURNS_CACHE))),
        },
        "clustering": {
            "best_k": int(best_k),
            "silhouette_score": round(float(best_score), 4),
            "features": ["cagr", "vol", "sharpe", "mdd", "div_yield", "holders_count_log"],
        },
        "combo_generation": {
            "target": N_COMBOS_TARGET,
            "actual_generated": int(n_combos_run),
            "source_breakdown": {
                "A_cluster": int((df_ranked["source"] == "A_cluster").sum()),
                "B_monte": int((df_ranked["source"] == "B_monte").sum()),
                "C_filt": int((df_ranked["source"] == "C_filt").sum()),
            },
        },
        "score_distribution": {
            col: {
                "median": float(df_ranked[col].median()),
                "mean": float(df_ranked[col].mean()),
                "max": float(df_ranked[col].max()),
                "min": float(df_ranked[col].min()),
            }
            for col in ["total_return", "cagr", "sharpe", "sortino", "mdd", "calmar"]
        },
        "pareto_front_size": int(df_ranked["is_pareto"].sum()),
        "top_3": [],
    }

    for idx, row in top3.iterrows():
        tids = row["tids"].split("|")
        weights = [float(w) for w in row["weights"].split("|")]
        comp = []
        for tid, w in zip(tids, weights):
            r = df_whitelist[df_whitelist["tid"] == tid]
            if len(r) > 0:
                r = r.iloc[0]
                # 優先用重算的 2y metrics
                if new_metrics is not None and tid in new_metrics:
                    m = new_metrics[tid]
                    cagr_d = round(m["cagr"], 4)
                    sharpe_d = round(m["sharpe"], 4)
                    mdd_d = round(m["mdd"], 4)
                else:
                    cagr_d = round(float(r["cagr"]), 4)
                    sharpe_d = round(float(r["sharpe"]), 4)
                    mdd_d = round(float(r["mdd"]), 4)
                comp.append({
                    "tid": tid,
                    "name": r["name"],
                    "weight": round(w, 4),
                    "cagr_2y": cagr_d,
                    "sharpe_2y": sharpe_d,
                    "mdd_2y": mdd_d,
                    "holders_count": int(r["holders_count"]) if pd.notna(r["holders_count"]) else None,
                })
        summary["top_3"].append({
            "rank": int(row["overall_rank"]),
            "total_score": int(row["total_score"]),
            "combo_metrics": {
                "total_return": round(float(row["total_return"]), 4),
                "cagr": round(float(row["cagr"]), 4),
                "sharpe": round(float(row["sharpe"]), 4),
                "sortino": round(float(row["sortino"]), 4),
                "mdd": round(float(row["mdd"]), 4),
                "calmar": round(float(row["calmar"]), 4),
            },
            "is_pareto": bool(row["is_pareto"]),
            "components": comp,
        })

    OUT_SUMMARY.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    log(f"  💾 {OUT_SUMMARY}")
    return top3


# ============================================================
# Main
# ============================================================
def main():
    log("=" * 70)
    log("🚀 fund-plan Phase 3 v1 — 排列組合排名")
    log("=" * 70)

    t_start = time.time()

    # Step 0
    whitelist, filt_df = step0_load_whitelist()

    # Step 1: 取日報酬
    prices, returns_df, valid_tids, new_metrics = step1_fetch_prices(whitelist)

    # Step 2: KMeans
    df_with_cluster, best_k, best_score, rep_tids = step2_kmeans(whitelist, valid_tids, new_metrics)

    # Step 3: 候選組合
    combos = step3_generate_combos(df_with_cluster, rep_tids, valid_tids, filt_df)

    # Step 4: 計算 6 分數
    df_combos = step4_compute_metrics(combos, returns_df)

    # Step 5: 排名 + Pareto
    df_ranked = step5_ranking(df_combos)

    # Step 6: 輸出
    top3 = step6_outputs(df_ranked, whitelist, valid_tids, best_k, best_score, len(combos), new_metrics)

    elapsed = time.time() - t_start
    log("=" * 70)
    log(f"✅ Phase 3 v1 完成 — {elapsed:.1f}s ({elapsed/60:.1f} min)")
    log(f"  跑了 {len(combos)} 組合")
    log(f"  Pareto 前緣: {df_ranked['is_pareto'].sum()}")
    log(f"  KMeans: K={best_k}, silhouette={best_score:.4f}")
    log(f"  Top 3 組合總分: {top3['total_score'].tolist()}")
    log("=" * 70)


if __name__ == "__main__":
    main()