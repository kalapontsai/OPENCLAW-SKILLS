#!/usr/bin/env python3
"""
fund-plan Phase 2 v7 — TDCC 集保戶數整合

主人 #5070：「集保戶數不作為門�，只作為參考資料」
→ 在 single_metrics_all.csv 新增 holders_count 欄位（nullable join）
→ 不動 single_metrics_filtered.csv 的 27 檔
→ 不動既有 5 門檻篩選邏輯

TDCC 來源：https://opendata.tdcc.com.tw/getOD.ashx?id=2-41
- 欄位（中文）：資料年月, 證券代號, 證券名稱, 本月底保管數, 前月底保管數,
              增減數額, 增減百分比, 發行單位數, 集保戶數
- 取最新月份（單檔單筆）
- 欄位英文化：security_code, security_name, custody_qty, holders_count,
              issued_units, month
"""
from __future__ import annotations
import sys, time
from pathlib import Path
import pandas as pd
import requests

PROJECT_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_DIR / "data"
OUT_DIR = PROJECT_DIR / "outputs"
TDCC_DIR = DATA_DIR / "tdcc"
LOG_DIR = PROJECT_DIR / "logs"

ALL_CSV = OUT_DIR / "single_metrics_all.csv"
FILT_CSV = OUT_DIR / "single_metrics_filtered.csv"
HOLDERS_CSV = TDCC_DIR / "etf_monthly_holders.csv"

TDCC_URL = "https://opendata.tdcc.com.tw/getOD.ashx?id=2-41"
TIMEOUT = 30

CN_COLS = [
    "資料年月", "證券代號", "證券名稱", "本月底保管數", "前月底保管數",
    "增減數額", "增減百分比", "發行單位數", "集保戶數",
]
EN_COLS = [
    "month", "security_code", "security_name", "custody_qty", "prev_custody_qty",
    "delta_qty", "delta_pct", "issued_units", "holders_count",
]


def log(msg: str) -> None:
    ts = time.strftime("%H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line, flush=True)
    (LOG_DIR / "phase2_tdcc.log").open("a", encoding="utf-8").write(line + "\n")


# ============================================================
# 1. 下載 TDCC CSV（UTF-8 BOM，CRLF，數字欄位帶多餘空白）
# ============================================================
def download_tdcc() -> Path:
    """下載完整 CSV 到 data/tdcc/etf_monthly_holders.csv。"""
    TDCC_DIR.mkdir(parents=True, exist_ok=True)
    log(f"📥 下載 TDCC 集保戶數: {TDCC_URL}")
    r = requests.get(TDCC_URL, timeout=TIMEOUT, headers={
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    })
    r.raise_for_status()
    raw = r.content
    # 確認 BOM
    if raw[:3] == b"\xef\xbb\xbf":
        log("  ✓ 偵測到 UTF-8 BOM")
    else:
        log(f"  ⚠ 未偵測 BOM（前 3 bytes: {raw[:3]!r}）")

    HOLDERS_CSV.write_bytes(raw)
    log(f"  💾 {HOLDERS_CSV} ({len(raw):,} bytes)")
    return HOLDERS_CSV


# ============================================================
# 2. 解析 + 取最新月份 + 欄位英文化
# ============================================================
def parse_latest_month(path: Path) -> pd.DataFrame:
    """讀 CSV、欄位英文化、取最新月份單檔單筆。"""
    df = pd.read_csv(path, encoding="utf-8-sig", dtype=str, skipinitialspace=True)
    log(f"  讀入 {len(df):,} 列；欄位：{list(df.columns)}")

    # 欄位英文化（已英文化 → 跳過；中文 → 對齊 CN_COLS 後 rename）
    mapping = {cn: en for cn, en in zip(CN_COLS, EN_COLS)}
    renamed = {}
    for c in df.columns:
        c_clean = c.strip()
        if c_clean in mapping:
            renamed[c] = mapping[c_clean]
        elif c_clean in EN_COLS:
            # 已是英文欄位，不動
            pass
        else:
            log(f"  ⚠ 未知欄位：{c!r}")
    if renamed:
        df = df.rename(columns=renamed)

    # 確保所有 EN_COLS 存在
    missing = [c for c in EN_COLS if c not in df.columns]
    if missing:
        raise ValueError(f"缺少欄位：{missing}（實際：{list(df.columns)}）")

    df = df[EN_COLS].copy()

    # 數值欄位 → int
    for c in ["custody_qty", "prev_custody_qty", "delta_qty", "issued_units", "holders_count"]:
        df[c] = pd.to_numeric(df[c].astype(str).str.replace(",", ""), errors="coerce")
    df["delta_pct"] = pd.to_numeric(df["delta_pct"], errors="coerce")
    df["month"] = pd.to_numeric(df["month"], errors="coerce").astype("Int64")

    # 證券代號去空白
    df["security_code"] = df["security_code"].astype(str).str.strip()

    # 取最新月份
    latest = int(df["month"].max())
    df_latest = df[df["month"] == latest].copy()
    log(f"  📅 最新月份：{latest}，{len(df_latest):,} 檔")

    # 單檔單筆（防呆：同月份同代號重複）
    dup = df_latest["security_code"].duplicated().sum()
    if dup > 0:
        log(f"  ⚠ 偵測到重複 {dup} 筆，保留第一筆")
        df_latest = df_latest.drop_duplicates(subset=["security_code"], keep="first")

    return df_latest


# ============================================================
# 3. Join 進 single_metrics_all.csv（不動既有指標）
# ============================================================
def join_into_all(holders: pd.DataFrame) -> None:
    """left-join holders_count 到 single_metrics_all.csv，保留所有 228 筆。"""
    if not ALL_CSV.exists():
        raise FileNotFoundError(f"{ALL_CSV} 不存在")

    df_all = pd.read_csv(ALL_CSV, encoding="utf-8-sig")
    df_all["tid"] = df_all["tid"].astype(str).str.strip()

    # 建 join key（小字典）
    hmap = dict(zip(
        holders["security_code"].astype(str),
        holders["holders_count"],
    ))

    # 加 holders_count 欄位（nullable，缺值留空）
    if "holders_count" in df_all.columns:
        log(f"  ⚠ holders_count 已存在，覆寫")
        df_all = df_all.drop(columns=["holders_count"])

    df_all["holders_count"] = df_all["tid"].map(hmap)
    # 保留欄位順序：原欄位 + holders_count 在最後
    cols = [c for c in df_all.columns if c != "holders_count"] + ["holders_count"]
    df_all = df_all[cols]

    df_all.to_csv(ALL_CSV, index=False, encoding="utf-8-sig")
    log(f"  💾 {ALL_CSV}（{len(df_all)} 列，含 holders_count）")


# ============================================================
# Main
# ============================================================
def main():
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log("=" * 60)
    log("🚀 Phase 2 v7 — TDCC 集保戶數整合（參考欄位）")
    log("=" * 60)

    path = download_tdcc()
    holders = parse_latest_month(path)

    # 寫入英文化後的「乾淨版」到同檔
    holders.to_csv(path, index=False, encoding="utf-8-sig")
    log(f"  💾 英文化後寫回 {path}")

    join_into_all(holders)

    # 驗證 filtered.csv 沒動
    if FILT_CSV.exists():
        df_filt = pd.read_csv(FILT_CSV, encoding="utf-8-sig")
        log(f"  ✓ {FILT_CSV} 仍是 {len(df_filt)} 檔（未動）")
        if "holders_count" in df_filt.columns:
            log(f"  ⚠ filtered.csv 多了 holders_count，移除")
            df_filt = df_filt.drop(columns=["holders_count"])
            df_filt.to_csv(FILT_CSV, index=False, encoding="utf-8-sig")
            log(f"  ✓ 移除完成")

    log("=" * 60)
    log("✅ Phase 2 v7 TDCC 整合完成")
    log("=" * 60)


if __name__ == "__main__":
    main()
