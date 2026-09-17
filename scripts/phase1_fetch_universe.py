#!/usr/bin/env python3
"""
fund-plan Phase 1: 抓台股 ETF 候選池 + 0050 smoke test

任務:
1. 從 .env 載入 FinMind token
2. 抓 TaiwanStockInfo，篩 type=ETF + listed_date <= 2019-01-01
3. 寫入 data/etf_universe_raw.csv
4. 抓 0050 收盤價 (2019-01-01 ~ 2024-12-31)
5. 抓 0050 年度配息 (2019 ~ 2024)
6. 寫入 logs/phase1.log
7. stdout 印出簡短摘要（給 agent 讀）

作者: 大寶 (agent-one)
日期: 2026-08-29
"""
import os
import sys
import json
import time
import logging
from pathlib import Path
from datetime import datetime

import requests
import pandas as pd

# ============================================================
# 路徑設定
# ============================================================
PROJECT_DIR = Path(__file__).resolve().parent.parent
ENV_PATH = Path("/mnt/d/OneDrive - Sampo Corporation/3.Data/5.python/finlab_tw_screener/.env")
DATA_DIR = PROJECT_DIR / "data"
PRICE_DIR = DATA_DIR / "price"
DIVIDEND_DIR = DATA_DIR / "dividend"
LOG_DIR = PROJECT_DIR / "logs"

for d in [DATA_DIR, PRICE_DIR, DIVIDEND_DIR, LOG_DIR]:
    d.mkdir(parents=True, exist_ok=True)

# ============================================================
# Logging
# ============================================================
LOG_FILE = LOG_DIR / "phase1.log"
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger("phase1")

# ============================================================
# Token 載入
# ============================================================
def load_token() -> str:
    """從 .env 載入 FINMIND_TOKEN"""
    if not ENV_PATH.exists():
        raise FileNotFoundError(f".env 不存在: {ENV_PATH}")
    token = None
    for line in ENV_PATH.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        if k.strip() == "FINMIND_TOKEN":
            token = v.strip()
            break
    if not token or token == "your_token_here" or len(token) < 10:
        raise ValueError(f"FINMIND_TOKEN 無效或未設定（請到 {ENV_PATH} 填入）")
    log.info(f"✅ Token 載入成功（長度 {len(token)}）")
    return token


# ============================================================
# FinMind API（包裝）
# ============================================================
class FinMind:
    BASE = "https://api.finmindtrade.com/api/v4/data"

    def __init__(self, token: str):
        self.token = token
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": "fund-plan/phase1"})

    def _get(self, params: dict, max_retry: int = 3) -> pd.DataFrame:
        """GET + retry on 429"""
        params = {"token": self.token, **params}
        for attempt in range(1, max_retry + 1):
            try:
                r = self.session.get(self.BASE, params=params, timeout=30)
                if r.status_code == 200:
                    data = r.json()
                    if "data" not in data:
                        log.warning(f"⚠️ 回應無 data 欄位: {data}")
                        return pd.DataFrame()
                    return pd.DataFrame(data["data"])
                elif r.status_code == 429:
                    wait = 60
                    log.warning(f"�️ 429 rate limit, sleep {wait}s (attempt {attempt}/{max_retry})")
                    time.sleep(wait)
                elif r.status_code == 402:
                    raise PermissionError(f"402 Token 過期或無效（請到 finmindtrade.com 會員中心更新）")
                else:
                    log.warning(f"⚠️ HTTP {r.status_code}: {r.text[:200]}")
                    time.sleep(5)
            except requests.RequestException as e:
                log.warning(f"⚠️ Request exception: {e}, retry {attempt}/{max_retry}")
                time.sleep(5)
        raise RuntimeError(f"❌ 連續 {max_retry} 次失敗，停止")

    def fetch_info(self) -> pd.DataFrame:
        return self._get({"dataset": "TaiwanStockInfo"})

    def fetch_price(self, stock_id: str, start: str, end: str) -> pd.DataFrame:
        return self._get({
            "dataset": "TaiwanStockPrice",
            "stock_id": stock_id,
            "start_date": start,
            "end_date": end,
        })

    def fetch_dividend(self, stock_id: str, start: str, end: str) -> pd.DataFrame:
        return self._get({
            "dataset": "TaiwanStockDividend",
            "stock_id": stock_id,
            "start_date": start,
            "end_date": end,
        })


# ============================================================
# 主流程
# ============================================================
def main():
    started_at = datetime.now()
    log.info("=" * 60)
    log.info("🚀 fund-plan Phase 1 啟動")
    log.info("=" * 60)

    try:
        token = load_token()
    except (FileNotFoundError, ValueError) as e:
        log.error(f"❌ {e}")
        sys.exit(1)

    fm = FinMind(token)

    # ------------------------------------------------------
    # Step 1: 抓 TaiwanStockInfo
    # ------------------------------------------------------
    log.info("📡 抓 TaiwanStockInfo...")
    df_info = fm.fetch_info()
    log.info(f"   原始筆數: {len(df_info)}, 欄位: {list(df_info.columns)}")

    # 篩 ETF — FinMind API 在 2026 已變更欄位：
    #   - `type` 欄位 = `twse`/`tpex`/`emerging`（市場別）
    #   - `industry_category` = `ETF`/`上櫃ETF`/`上櫃指數股票型基金(ETF)` 等（正確 ETF 識別）
    if "industry_category" in df_info.columns:
        df_etf = df_info[
            df_info["industry_category"].str.contains("ETF", na=False)
        ].copy()
        log.info(f"   篩 industry_category 含 'ETF': {len(df_etf)} 檔")
    elif "type" in df_info.columns:
        df_etf = df_info[df_info["type"] == "ETF"].copy()
        log.info(f"   篩 type=ETF: {len(df_etf)} 檔")
    else:
        # 備援：直接看 stock_id（台股 ETF 都是 4 碼數字且常見 005x/006x/007x/008x/009x 開頭）
        log.warning("⚠️ 無 'industry_category'/'type' 欄位，採備援篩選")
        df_etf = df_info[
            df_info["stock_id"].str.match(r"^00[5-9]\d$", na=False)
        ].copy()
        log.info(f"   備援篩選: {len(df_etf)} 檔")

    # 篩上市 ≥ 2019-01-01
    if "listed_date" in df_etf.columns:
        before = len(df_etf)
        df_etf = df_etf[df_etf["listed_date"] <= "2019-01-01"].copy()
        log.info(f"   篩 listed_date ≤ 2019-01-01: {before} → {len(df_etf)} 檔")

    out_csv = DATA_DIR / "etf_universe_raw.csv"
    # 標準化欄位名稱：下游 (phase 2/3) 預期 tid / name / category
    # FinMind 2026 改用 stock_id / stock_name / industry_category / type
    df_out = df_etf.rename(columns={
        "stock_id": "tid",
        "stock_name": "name",
        "industry_category": "category",
    })
    df_out.to_csv(out_csv, index=False, encoding="utf-8-sig")
    log.info(f"💾 寫入 {out_csv}（欄位: {list(df_out.columns)}）")

    # 列前 10 檔
    if len(df_out) > 0:
        cols_show = [c for c in ["tid", "name", "category", "type"] if c in df_out.columns]
        log.info(f"   前 10 檔:\n{df_out[cols_show].head(10).to_string(index=False)}")

    # ------------------------------------------------------
    # Step 2: 0050 smoke test (graceful — 不讓 smoke test 失敗拖垮整個 phase 1)
    # ------------------------------------------------------
    log.info("=" * 60)
    log.info("🔥 0050 smoke test")
    log.info("=" * 60)

    START = "2019-01-01"
    END = "2024-12-31"

    df_price = pd.DataFrame()
    df_div = pd.DataFrame()
    smoke_status = "ok"

    try:
        log.info("📡 抓 0050 收盤價 (2019-2024)...")
        df_price = fm.fetch_price("0050", START, END)
        log.info(f"   收盤筆數: {len(df_price)}, 欄位: {list(df_price.columns)}")
        if len(df_price) > 0:
            log.info(f"   日期範圍: {df_price['date'].min()} ~ {df_price['date'].max()}")
            price_path = PRICE_DIR / "0050.csv"
            df_price.to_csv(price_path, index=False, encoding="utf-8-sig")
            log.info(f"💾 寫入 {price_path}")
    except (RuntimeError, PermissionError) as e:
        smoke_status = f"price_failed:{type(e).__name__}"
        log.warning(f"⚠️ 0050 price fetch 失敗: {e}")
        log.warning(f"   → 跳到 phase 2 走 Flask cache / yfinance fallback")

    try:
        log.info("📡 抓 0050 配息 (2019-2024)...")
        df_div = fm.fetch_dividend("0050", START, END)
        log.info(f"   配息筆數: {len(df_div)}, 欄位: {list(df_div.columns)}")
        if len(df_div) > 0:
            log.info(f"   配息明細:\n{df_div.to_string(index=False)}")
            div_path = DIVIDEND_DIR / "0050.csv"
            df_div.to_csv(div_path, index=False, encoding="utf-8-sig")
            log.info(f"💾 寫入 {div_path}")
    except (RuntimeError, PermissionError) as e:
        smoke_status += f";div_failed:{type(e).__name__}"
        log.warning(f"⚠️ 0050 dividend fetch 失敗: {e}")

    # ------------------------------------------------------
    # 完成摘要（給 agent 讀）
    # ------------------------------------------------------
    elapsed = (datetime.now() - started_at).total_seconds()
    summary = {
        "etf_count": len(df_etf),
        "etf_sample": df_etf["stock_id"].head(10).tolist() if len(df_etf) > 0 else [],
        "price_0050_rows": len(df_price),
        "price_0050_range": [df_price["date"].min(), df_price["date"].max()] if len(df_price) > 0 else None,
        "dividend_0050_rows": len(df_div),
        "elapsed_sec": round(elapsed, 1),
        "token_valid": True,
        "smoke_test_status": smoke_status,
    }
    summary_path = LOG_DIR / "phase1_summary.json"
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    log.info(f"💾 摘要寫入 {summary_path}")
    log.info("=" * 60)
    log.info(f"✅ Phase 1 完成（{elapsed:.1f}s）")
    log.info("=" * 60)


if __name__ == "__main__":
    main()
