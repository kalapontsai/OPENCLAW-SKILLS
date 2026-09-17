#!/usr/bin/env python3
"""
fund-plan Phase 2 v7 — TWSE 基金基本資料彙總表 整合

來源：https://mopsfin.twse.com.tw/opendata/t187ap47_L.csv
- 上市（含主動式）ETF 全列：欄位含「指數股票型基金」或「主動式交易所交易基金」
- 比對 data/etf_universe_raw.csv（228 檔）：
  - 找出漏檔（TWSE 有，universe 沒有）
  - 找出異檔（universe 有，TWSE 沒有）
- 不修改 universe / metrics；僅產出 diff CSV 供主人裁示
"""
from __future__ import annotations
import sys, time
from pathlib import Path
import pandas as pd
import requests

PROJECT_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_DIR / "data"
TWSE_DIR = DATA_DIR / "twse"
LOG_DIR = PROJECT_DIR / "logs"

UNIVERSE_CSV = DATA_DIR / "etf_universe_raw.csv"
FUND_BASIC_CSV = TWSE_DIR / "fund_basic.csv"
ETF_LIST_CSV = TWSE_DIR / "etf_list.csv"
DIFF_CSV = TWSE_DIR / "etf_universe_diff.csv"

TWSE_URL = "https://mopsfin.twse.com.tw/opendata/t187ap47_L.csv"
TIMEOUT = 30

# 11 種基金類型全部視為 ETF-like（含指數股票型 + 主動式交易所交易基金 + 期貨信託）
ETF_TYPE_KEYWORDS = ["指數股票型基金", "主動式交易所交易基金", "期貨信託基金"]


def log(msg: str) -> None:
    ts = time.strftime("%H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line, flush=True)
    (LOG_DIR / "phase2_twse.log").open("a", encoding="utf-8").log if False else None
    (LOG_DIR / "phase2_twse.log").open("a", encoding="utf-8").write(line + "\n")


# ============================================================
# 1. 下載 TWSE 基金基本資料
# ============================================================
def download_twse() -> Path:
    TWSE_DIR.mkdir(parents=True, exist_ok=True)
    log(f"📥 下載 TWSE 基金基本資料: {TWSE_URL}")
    r = requests.get(TWSE_URL, timeout=TIMEOUT, headers={
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    })
    r.raise_for_status()
    raw = r.content
    FUND_BASIC_CSV.write_bytes(raw)
    log(f"  💾 {FUND_BASIC_CSV} ({len(raw):,} bytes)")
    return FUND_BASIC_CSV


# ============================================================
# 2. 解析 + 篩選 ETF
# ============================================================
def parse_etf_list(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path, encoding="utf-8-sig", dtype=str)
    log(f"  讀入 {len(df):,} 列基金")
    log(f"  基金類型分布：")
    vc = df["基金類型"].value_counts()
    for t, n in vc.items():
        log(f"    {t}: {n}")

    # �選 ETF（含 指數股票型基金 或 主動式交易所交易基金）
    mask = df["基金類型"].str.contains("|".join(ETF_TYPE_KEYWORDS), na=False)
    df_etf = df[mask].copy()
    log(f"  篩選 ETF 後：{len(df_etf)} 檔")

    df_etf["基金代號"] = df_etf["基金代號"].astype(str).str.strip()
    return df_etf


# ============================================================
# 3. 比對 universe
# ============================================================
def diff_vs_universe(df_etf: pd.DataFrame) -> pd.DataFrame:
    if not UNIVERSE_CSV.exists():
        raise FileNotFoundError(f"{UNIVERSE_CSV} 不存在")

    df_uni = pd.read_csv(UNIVERSE_CSV, encoding="utf-8-sig")
    df_uni["tid"] = df_uni["tid"].astype(str).str.strip()

    twse_tids = set(df_etf["基金代號"])
    uni_tids = set(df_uni["tid"])

    # 漏檔：TWSE 有，universe 沒有
    missing = sorted(twse_tids - uni_tids)
    # 異檔：universe 有，TWSE 沒有
    extra = sorted(uni_tids - twse_tids)

    log(f"  📊 比對結果：")
    log(f"    TWSE ETF: {len(twse_tids)} 檔")
    log(f"    Universe: {len(uni_tids)} 檔")
    log(f"    Intersect: {len(twse_tids & uni_tids)} 檔")
    log(f"    TWSE 有 / Universe 沒有（漏檔）: {len(missing)} 檔")
    log(f"    Universe 有 / TWSE 沒有（異檔）: {len(extra)} 檔")

    # 建輸出表
    etf_lookup = df_etf.set_index("基金代號")[["基金簡稱", "基金類型", "上市日期"]].to_dict("index")

    rows = []
    for tid in missing:
        info = etf_lookup.get(tid, {})
        rows.append({
            "tid": tid,
            "name": info.get("基金簡稱", ""),
            "fund_type": info.get("基金類型", ""),
            "list_date": info.get("上市日期", ""),
            "diff_type": "missing_in_universe",
            "note": "TWSE 有，Universe 沒有 — 考慮補入",
        })
    for tid in extra:
        uni_info = df_uni[df_uni["tid"] == tid].iloc[0] if (df_uni["tid"] == tid).any() else {}
        rows.append({
            "tid": tid,
            "name": uni_info.get("name", ""),
            "fund_type": "",
            "list_date": "",
            "diff_type": "missing_in_twse",
            "note": "Universe 有，TWSE 沒有 — 多為上櫃債券 (TPEx) 或下市",
        })

    return pd.DataFrame(rows)


# ============================================================
# Main
# ============================================================
def main():
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log("=" * 60)
    log("🚀 Phase 2 v7 — TWSE 基金基本資料整合（漏檔 / 異檔 比對）")
    log("=" * 60)

    path = download_twse()
    df_etf = parse_etf_list(path)

    # 寫入乾淨版 ETF list（保留原欄位，方便 Phase 3 引用）
    df_etf.to_csv(ETF_LIST_CSV, index=False, encoding="utf-8-sig")
    log(f"  💾 {ETF_LIST_CSV}（{len(df_etf)} 檔）")

    # 比對
    diff = diff_vs_universe(df_etf)
    diff.to_csv(DIFF_CSV, index=False, encoding="utf-8-sig")
    log(f"  � {DIFF_CSV}（{len(diff)} 筆差異）")

    log("=" * 60)
    log("✅ Phase 2 v7 TWSE 整合完成")
    log("=" * 60)


if __name__ == "__main__":
    main()
