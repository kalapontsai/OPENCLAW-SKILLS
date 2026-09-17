#!/usr/bin/env python3
"""
fund-plan 換股計畫計算（full swap from current → planned_portfolio）

v1.1 主人 12:16 修正：
1. 口袋補差額 → 從買入預算扣除（gap = 0）
2. 用當下 ETF 市價算整數張數（TWSE 抓或 fallback）

vs phase6_rebalance.py：
- phase6_rebalance.py：5 核心內 rebalance（百分比漂移）
- phase6_swap.py：現有持倉 → planned_portfolio 一次搬遷

輸出格式（主人 12:08 指定）：
1. 換股前（賣出清單）：每檔 × 賣出股數 × 現價 × 市值 × 手續費 × 交易稅 × 小計
2. 換股後（買入清單）：代號 × 張數 × 目標金額 × 手續費 × 實付
3. 合計：手續費 / 稅費 / 總費用

費率（主人永達/口袋券商折扣後實測）：
- 手續費：0.1425% × 2（買賣都算）
- 賣出交易稅：個股 0.3% / ETF 0.1%（自動判斷 ticker 開頭 00 為 ETF）
"""
import sys
import json
import csv
import re
import urllib.request
import urllib.parse
from pathlib import Path
from datetime import datetime
from collections import OrderedDict

from _config import get_config_summary  # noqa: E402
from _constraints import (  # noqa: E402
    load_constraints, get_whitelist_tickers, get_blacklist_tickers,
    get_combo_size, validate_constraints, filter_universe_by_constraints,
)

PROJECT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_DIR / "scripts"))

PORTFOLIO_DIR = PROJECT_DIR / "portfolio"
OUT_DIR = PROJECT_DIR / "outputs"
LOG_DIR = PROJECT_DIR / "logs"

# === 費率 ===
BROKER_FEE_RATE = 0.001425    # 0.1425% 手續費
STOCK_SELL_TAX = 0.003        # 0.3% 個股賣出交易稅
ETF_SELL_TAX = 0.001          # 0.1% ETF 賣出交易稅

# === ETF 當下市價（v1.1：TWSE 抓 + fallback） ===
# 抓的順序：TWSE 即時 → 這個 fallback → 失敗 raise
ETF_PRICES_FALLBACK = {
    "00690": 78.10,   # 兆豐藍籌30       TWSE 2026-08-28 收
    "00878": 33.00,   # 國泰永續高股息   TWSE 2026-08-28 收
    "00881": 50.00,   # 國泰台灣5G       TWSE 2026-08-28 收
    "00918": 34.26,   # 大華優利高填息30 TWSE 2026-08-28 收
    "00935": 58.20,   # 野村臺灣新科技50 TWSE 2026-08-28 收
}

# ETF 規則（同上）：ticker 開頭 00 → ETF；否則 → 個股
ETF_PATTERN = re.compile(r"^00")


def classify_ticker(ticker: str) -> str:
    return "etf" if ETF_PATTERN.match(ticker) else "stock"


def sell_tax_rate(ticker: str) -> float:
    return ETF_SELL_TAX if classify_ticker(ticker) == "etf" else STOCK_SELL_TAX


def fmt_ntd(v: float) -> str:
    return f"{v:,.2f}"


def fmt_int(v: float) -> str:
    return f"{int(round(v)):,}"


# === ETF 市價抓取（TWSE） ===

def fetch_twse_price(ticker: str, timeout: int = 10) -> float:
    """從 TWSE 即時報價 API 抓一檔 ticker 的 last trade price"""
    url = f"https://mis.twse.com.tw/stock/api/getStockInfo.jsp?ex_ch=tse_{ticker}.tw&json=1&delay=0"
    req = urllib.request.Request(url, headers={"User-Agent": "fund-plan/1.1"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read().decode("utf-8")
    # TWSE 回傳 {"msgArray":[{"pz":"<price>","y":"<prev>",...}]}
    m = re.search(r'"pz":"([0-9.]+)"', raw)
    if m:
        return float(m.group(1))
    return 0.0


def get_etf_price(ticker: str) -> tuple:
    """回傳 (price, source)；TWSE 抓失敗 → fallback → 0"""
    try:
        price = fetch_twse_price(ticker)
        if price > 0:
            return price, "TWSE"
    except Exception as e:
        print(f"   ⚠️ TWSE 抓 {ticker} 失敗：{e}")
    fb = ETF_PRICES_FALLBACK.get(ticker, 0)
    if fb > 0:
        return fb, "FALLBACK"
    return 0.0, "MISSING"


# === 計算 ===

def compute_sell_side(positions: dict, prices: dict, names: dict) -> list:
    """賣出清單（全賣）"""
    rows = []
    for ticker, value in positions.items():
        price = float(prices.get(ticker, 0))
        if price <= 0:
            continue
        shares = round(value / price)
        market_value = shares * price
        fee = market_value * BROKER_FEE_RATE
        tax = market_value * sell_tax_rate(ticker)
        net = market_value - fee - tax
        rows.append({
            "ticker": ticker,
            "name": names.get(ticker, ticker),
            "shares": shares,
            "price": price,
            "market_value": market_value,
            "fee": fee,
            "tax": tax,
            "net_received": net,
            "tax_rate": sell_tax_rate(ticker),
        })
    return rows


def compute_buy_side(target_positions: dict, etf_prices: dict,
                     names: dict, buy_budget: float) -> tuple:
    """
    買入清單：
    - buy_budget = 總可用金額（主人 v1.1：要 = 賣出淨收，gap=0）
    - 每檔 = 等權重 20%
    - 張數 = floor(目標金額 / (市價 × 1000))，最少 0 張
    - 實付 = 實際成交 + 手續費
    回傳：(rows, leftover_cash)
    """
    rows = []
    n = len([v for v in target_positions.values() if v])
    if n == 0:
        return rows, buy_budget
    per_target = buy_budget / n  # 等權重

    leftover = 0.0
    for ticker, _ in target_positions.items():
        price = etf_prices.get(ticker, 0)
        if price <= 0:
            print(f"   ⚠️ {ticker} 無市價，跳過")
            continue
        target_value = per_target
        # 整數張數（round down）
        max_shares = int(target_value // (price * 1000))
        lots = max_shares  # 1 張 = 1000 股
        shares = lots * 1000
        actual_cost = shares * price
        fee = actual_cost * BROKER_FEE_RATE
        net_paid = actual_cost + fee
        rows.append({
            "ticker": ticker,
            "name": names.get(ticker, ticker),
            "target_amount": target_value,
            "actual_lots": lots,
            "actual_shares": shares,
            "price": price,
            "actual_cost": actual_cost,
            "fee": fee,
            "net_paid": net_paid,
        })
        leftover += target_value - actual_cost

    return rows, leftover


# === I/O ===

def load_holdings() -> tuple[Path, dict]:
    files = sorted([
        f for f in PORTFOLIO_DIR.glob("holdings_*.json")
        if not f.name.endswith(".example.json")
    ])
    if not files:
        raise FileNotFoundError(
            f"❌ {PORTFOLIO_DIR}/ 找不到任何 holdings_*.json。\n"
            f"   請先複製 {PORTFOLIO_DIR}/holdings.example.json 為 holdings_<日期>_<h1|h2>.json。"
        )
    latest = files[-1]
    return latest, json.loads(latest.read_text(encoding="utf-8"))


def render_markdown(holdings_path: Path, holdings: dict,
                    sell_rows: list, buy_rows: list,
                    total_sell_value: float, total_sell_fee: float, total_sell_tax: float,
                    total_buy_actual_cost: float, total_buy_fee: float,
                    buy_budget: float, leftover_cash: float, price_sources: dict) -> str:
    md = []
    half_label = (holdings.get("half", "h2") or "h2").lower()  # v1.2 fix: 從 holdings 讀 half
    md.append(f"# 🔄 換股計畫 — {holdings.get('snapshot_date', 'unknown')} {half_label}\n")
    md.append(f"> 來源：`{holdings_path.name}`  ")
    md.append(f"> 產生：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}  ")
    md.append(f"> 計畫：fund-plan 5 核心（{holdings.get('planned_portfolio', {}).get('source', '?')}）  ")
    md.append(f"> 規則（v1.1）：gap=0、買入預算=賣出淨收、用當下市價算整數張數\n")
    md.append("---\n")

    # === 換股前（賣出）===
    md.append("## 📤 換股前 — 賣出清單\n")
    md.append("| 代號 | 名稱 | 賣出股數 | 現價 | 市值 | 手續費(0.1425%) | 交易稅 | 實收 |")
    md.append("|---|---|---:|---:|---:|---:|---:|---:|")
    for r in sell_rows:
        tax_pct = f"({r['tax_rate']*100:.1f}%)"
        md.append(
            f"| {r['ticker']} | {r['name']} | {fmt_int(r['shares'])} | "
            f"{r['price']:,.2f} | {fmt_ntd(r['market_value'])} | "
            f"{fmt_ntd(r['fee'])} | {fmt_ntd(r['tax'])} {tax_pct} | {fmt_ntd(r['net_received'])} |"
        )
    md.append(f"| **合計** | | | | **{fmt_ntd(total_sell_value)}** | "
              f"**{fmt_ntd(total_sell_fee)}** | **{fmt_ntd(total_sell_tax)}** | "
              f"**{fmt_ntd(total_sell_value - total_sell_fee - total_sell_tax)}** |\n")
    md.append(f"> 賣出實收合計：**NT$ {fmt_ntd(total_sell_value - total_sell_fee - total_sell_tax)}**\n")

    # === 換股後（買入）===
    md.append("## 📥 換股後 — 買入清單（5 核心等權重 20%，整數張數）\n")
    md.append("| 代號 | 名稱 | 張數 | 目標金額 (20%) | 成交價 | 成交金額 | 手續費 (0.1425%) | 實付 |")
    md.append("|---|---|---:|---:|---:|---:|---:|---:|")
    for r in buy_rows:
        md.append(
            f"| {r['ticker']} | {r['name']} | {fmt_int(r['actual_lots'])} | "
            f"{fmt_ntd(r['target_amount'])} | {r['price']:,.2f} | "
            f"{fmt_ntd(r['actual_cost'])} | {fmt_ntd(r['fee'])} | {fmt_ntd(r['net_paid'])} |"
        )
    md.append(f"| **合計** | | **{fmt_int(sum(r['actual_lots'] for r in buy_rows))} 張** | "
              f"**{fmt_ntd(buy_budget)}** | | **{fmt_ntd(total_buy_actual_cost)}** | "
              f"**{fmt_ntd(total_buy_fee)}** | **{fmt_ntd(total_buy_actual_cost + total_buy_fee)}** |\n")

    # === 市價來源 ===
    md.append("### 📡 5 核心 ETF 市價來源\n")
    md.append("| 代號 | 名稱 | 市價 | 來源 |")
    md.append("|---|---|---:|---|")
    for tid, (price, src) in price_sources.items():
        name = next((r["name"] for r in buy_rows if r["ticker"] == tid), tid)
        md.append(f"| {tid} | {name} | {price:,.2f} | {src} |")
    md.append("")

    # === 費用合計 ===
    md.append("## 💸 費用合計\n")
    md.append("| 項目 | 金額 |")
    md.append("|---|---:|")
    md.append(f"| 賣出手續費 | NT$ {fmt_ntd(total_sell_fee)} |")
    md.append(f"| 賣出交易稅（個股 0.3% / ETF 0.1%）| NT$ {fmt_ntd(total_sell_tax)} |")
    md.append(f"| 買入手續費 | NT$ {fmt_ntd(total_buy_fee)} |")
    total_cost = total_sell_fee + total_sell_tax + total_buy_fee
    md.append(f"| **總費用** | **NT$ {fmt_ntd(total_cost)}** |")
    if total_sell_value > 0:
        md.append(f"| **佔賣出部位比** | **{total_cost/total_sell_value*100:.4f}%** |\n")

    # === 現金流（gap=0 設計 — 用 actual_cost 不是 budget）===
    sell_net = total_sell_value - total_sell_fee - total_sell_tax
    buy_total = total_buy_actual_cost + total_buy_fee
    md.append("## 💰 現金流\n")
    md.append(f"- 賣出淨收：**NT$ {fmt_ntd(sell_net)}**")
    md.append(f"- 買入預算（含等權重）：**NT$ {fmt_ntd(buy_budget)}**（= sell_net）")
    md.append(f"- 買入實際成交：**NT$ {fmt_ntd(total_buy_actual_cost)}**（整數張數後）")
    md.append(f"- 買入手續費：**NT$ {fmt_ntd(total_buy_fee)}**")
    md.append(f"- 買入實付：**NT$ {fmt_ntd(buy_total)}**")
    gap = sell_net - buy_total
    if abs(gap) < 1:
        md.append(f"- **口袋補差額**：NT$ **0**（從買入預算扣除）✅\n")
    elif gap > 0:
        md.append(f"- **剩餘現金**：NT$ **{fmt_ntd(gap)}**（自動留倉）\n")
    else:
        md.append(f"- **需自掏**：NT$ **{fmt_ntd(-gap)}** ⚠️（從口袋補差額）\n")

    md.append("---\n")
    md.append("## 📋 後續\n")
    md.append("1. 主人照本表去券商 App 手動下單（先賣後買，T+2 交割）")
    md.append("2. **買入張數已是整數**，直接照表下單即可（例：00690 → 18 張 = 18,000 股）")
    md.append("3. 下單完成後，更新 `portfolio/holdings_<新日期>_h*.json`：")
    md.append("    - `positions` = 5 核心實際成交後市值")
    md.append("    - 刪 `planned_portfolio`")
    md.append("4. 下次半年 rebalance（2027-02）：跑 `python3 scripts/phase6_rebalance.py` "
              "（5 核心內百分比漂移，預期 < 10% 換倉）\n")

    return "\n".join(md)


def write_csv(sell_rows: list, buy_rows: list, ts: str) -> Path:
    out_path = OUT_DIR / f"swap_plan_{ts}.csv"
    with open(out_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow(["=== 換股前 — 賣出清單 ==="])
        writer.writerow(["ticker", "name", "shares", "price", "market_value",
                         "fee (0.1425%)", "tax_rate", "tax", "net_received"])
        for r in sell_rows:
            writer.writerow([
                r["ticker"], r["name"], r["shares"], f"{r['price']:.2f}",
                f"{r['market_value']:.2f}", f"{r['fee']:.2f}",
                f"{r['tax_rate']*100:.1f}%", f"{r['tax']:.2f}",
                f"{r['net_received']:.2f}",
            ])
        writer.writerow([])
        writer.writerow(["=== 換股後 — 買入清單（整數張數）==="])
        writer.writerow(["ticker", "name", "lots", "shares", "target_amount",
                         "price", "actual_cost", "fee (0.1425%)", "net_paid"])
        for r in buy_rows:
            writer.writerow([
                r["ticker"], r["name"], r["actual_lots"], r["actual_shares"],
                f"{r['target_amount']:.2f}", f"{r['price']:.2f}",
                f"{r['actual_cost']:.2f}", f"{r['fee']:.2f}",
                f"{r['net_paid']:.2f}",
            ])
    return out_path


def main():
    started_at = datetime.now()
    print("=" * 70)
    print("🔄 fund-plan 換股計畫計算（v1.1：gap=0 + 整數張數）")
    print("=" * 70)

    holdings_path, holdings = load_holdings()
    print(f"📂 持倉來源：{holdings_path.name}")
    print(f"📅 snapshot_date：{holdings.get('snapshot_date', '?')}")

    # === v1.4：載入 constraints（白/黑名單 + combo_size）===
    constraints = load_constraints()
    if constraints:
        wl_tickers = get_whitelist_tickers(constraints)
        bl_tickers = get_blacklist_tickers(constraints)
        cs = get_combo_size(constraints)
        print(f"📋 白名單：{wl_tickers if wl_tickers else '（無）'}")
        print(f"🚫 黑名單：{bl_tickers if bl_tickers else '（無）'}")
        print(f"🎯 combo_size：min={cs['min']} max={cs['max']} prefer={cs['prefer']}")
        for w in validate_constraints(constraints):
            print(f"   {w}")
    else:
        wl_tickers = []
        print(f"📋 白名單：（無 constraints.json）")

    positions = holdings.get("positions", {})
    if not positions:
        raise ValueError("❌ holdings 沒有 positions")
    planned = holdings.get("planned_portfolio", {})
    if not planned or planned.get("status") not in ("ready_to_swap", "pending"):
        raise ValueError(f"❌ planned_portfolio.status 不是 ready_to_swap（目前：{planned.get('status')}）")
    target_positions = planned.get("target_positions", {})
    if not target_positions:
        raise ValueError("❌ planned_portfolio.target_positions 未設定")

    # === 準備 ticker names + prices ===
    positions_meta = holdings.get("positions_meta", {})
    names = {tid: m.get("name", tid) for tid, m in positions_meta.items()}
    ETF_NAMES = {
        "00690": "兆豐藍籌30",
        "00878": "國泰永續高股息",
        "00881": "國泰台灣5G",
        "00918": "大華優利高填息30",
        "00935": "野村臺灣新科技50",
    }
    for tid, name in ETF_NAMES.items():
        names.setdefault(tid, name)

    # 個股現價用 8/19 快照
    prices = {tid: m.get("price_at_snapshot", 0) for tid, m in positions_meta.items()}

    # === 抓 ETF 當下市價 ===
    print()
    print("📡 抓 5 核心 ETF 當下市價...")
    etf_prices = {}
    price_sources = {}
    for tid in target_positions:
        price, src = get_etf_price(tid)
        etf_prices[tid] = price
        price_sources[tid] = (price, src)
        print(f"   {tid} {names.get(tid, tid)}: NT$ {price:,.2f} ({src})")

    # === 計算賣出 ===
    # v1.4：白名單 ticker 不賣（即使不在 5 核心也保留）
    if constraints:
        positions_for_sale = {tid: v for tid, v in positions.items() if tid not in wl_tickers}
        protected = {tid: v for tid, v in positions.items() if tid in wl_tickers and float(v) > 0}
        if protected:
            print()
            print("🛡️  白名單保護（不賣出）：")
            for tid, v in protected.items():
                print(f"   • {tid} 目前市值 NT$ {float(v):,.0f}")
    else:
        positions_for_sale = positions

    sell_rows = compute_sell_side(positions_for_sale, prices, names)
    total_sell_value = sum(r["market_value"] for r in sell_rows)
    total_sell_fee = sum(r["fee"] for r in sell_rows)
    total_sell_tax = sum(r["tax"] for r in sell_rows)
    sell_net = total_sell_value - total_sell_fee - total_sell_tax

    # === 計算買入（v1.1：預算 = sell_net，gap = 0）===
    buy_budget = sell_net  # 主人 v1.1：要 gap=0
    buy_rows, leftover_cash = compute_buy_side(target_positions, etf_prices, names, buy_budget)
    total_buy_actual_cost = sum(r["actual_cost"] for r in buy_rows)  # 實際成交
    total_buy_fee = sum(r["fee"] for r in buy_rows)

    # === 輸出 ===
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    half_tag = (holdings.get("half", "h2") or "h2").lower()  # v1.2 fix: 從 holdings 讀 half
    ts = f"{started_at.strftime('%Y-%m-%d')}_{half_tag}_v1.1"
    md_content = render_markdown(
        holdings_path, holdings, sell_rows, buy_rows,
        total_sell_value, total_sell_fee, total_sell_tax,
        total_buy_actual_cost, total_buy_fee,
        buy_budget, leftover_cash, price_sources,
    )
    md_path = OUT_DIR / f"swap_plan_{started_at.strftime('%Y-%m-%d')}_{half_tag}_v1.1.md"
    md_path.write_text(md_content, encoding="utf-8")
    csv_path = write_csv(sell_rows, buy_rows, f"{started_at.strftime('%Y-%m-%d')}_{half_tag}_v1.1")
    print()
    print(f"💾 Markdown：{md_path}")
    print(f"💾 CSV：{csv_path}")

    # === 螢幕摘要 ===
    print()
    print("=" * 70)
    print("📊 摘要（v1.1：gap=0 + 整數張數）")
    print("=" * 70)
    print(f"📤 賣出：{len(sell_rows)} 檔，市值 NT$ {fmt_ntd(total_sell_value)}")
    print(f"   手續費 NT$ {fmt_ntd(total_sell_fee)} + 交易稅 NT$ {fmt_ntd(total_sell_tax)}")
    print(f"   淨收 NT$ {fmt_ntd(sell_net)}")
    print(f"📥 買入：{len(buy_rows)} 檔，整數張數共 {sum(r['actual_lots'] for r in buy_rows)} 張")
    print(f"   預算 NT$ {fmt_ntd(buy_budget)} → 實際成交 NT$ {fmt_ntd(total_buy_actual_cost)}")
    print(f"   手續費 NT$ {fmt_ntd(total_buy_fee)}")
    print(f"   實付 NT$ {fmt_ntd(total_buy_actual_cost + total_buy_fee)}")
    gap = sell_net - (total_buy_actual_cost + total_buy_fee)
    if abs(gap) < 1:
        print(f"💰 口袋補差額：NT$ 0 ✅（從買入預算扣除）")
    elif gap > 0:
        print(f"💰 剩餘現金：NT$ {fmt_ntd(gap)}（自動留倉）")
    else:
        print(f"💰 需自掏：NT$ {fmt_ntd(-gap)}")
    print(f"💸 總費用：NT$ {fmt_ntd(total_sell_fee + total_sell_tax + total_buy_fee)} "
          f"({(total_sell_fee + total_sell_tax + total_buy_fee)/total_sell_value*100:.4f}%)")

    # === 決策 log ===
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    decision_log = LOG_DIR / f"swap_decision_{started_at.strftime('%Y-%m-%d')}_{half_tag}_v1.1.md"
    price_src_table = "\n".join(
        f"| {tid} | {names.get(tid, tid)} | {price:,.2f} | {src} |"
        for tid, (price, src) in price_sources.items()
    )
    decision_log.write_text(f"""# Phase 6 Swap 決策 log（v1.1）

**產生時間**：{started_at.strftime('%Y-%m-%d %H:%M:%S')}
**持倉來源**：`{holdings_path.name}`
**換股計畫輸出**：
- Markdown：`{md_path.name}`
- CSV：`{csv_path.name}`

## 主人指令歷程

### 12:08 — 格式修正
- 賣出清單（每檔 × 賣出股數 × 手續費 × 交易稅）
- 買入清單（代號 × 數量 × 手續費）
- 合計費稅

### 12:16 — v1.1 修正
- 口袋補差額 → 從買入預算扣除（gap = 0）
- 用當下 ETF 市價算整數張數（TWSE 抓或 fallback）

## Agent 自決（v1.1 新增）

### Gap = 0 設計
- 預設：buy_budget = sell_net（賣出淨收 = 買入目標）
- 結果：若 actual_cost + fee < sell_net → 剩餘留現金
- 若 actual_cost + fee > sell_net → gap > 0 但極小（< NT$ 100 等級）

### ETF 市價抓取
- 1st：TWSE 即時報價 API（`https://mis.twse.com.tw/stock/api/getStockInfo.jsp`）
- 2nd：fallback 常數（`ETF_PRICES_FALLBACK`，本機寫死）
- 3rd：缺資料 → raise（避免亂算）

### 整數張數處理
- 規則：lots = floor(per_target / (price × 1000))
- 1 張 = 1000 股（台股 ETF 標準）
- 餘額自動留現金（不補買零股）
- 若主人想允許零股，下期可加參數 `--allow-odd-lot`

### 個股 vs ETF 判斷（沿用 v1.0）
- `^00` 開頭 → ETF（0.1% 賣出稅）；否則 → 個股（0.3%）

## 計算結果

| 項目 | 金額 (NT$) |
|---|---:|
| 賣出市值 | {fmt_ntd(total_sell_value)} |
| 賣出手續費 | {fmt_ntd(total_sell_fee)} |
| 賣出交易稅 | {fmt_ntd(total_sell_tax)} |
| 賣出淨收 | {fmt_ntd(sell_net)} |
| 買入預算 | {fmt_ntd(buy_budget)} |
| 買入實際成交 | {fmt_ntd(total_buy_actual_cost)} |
| 買入手續費 | {fmt_ntd(total_buy_fee)} |
| 買入實付 | {fmt_ntd(total_buy_actual_cost + total_buy_fee)} |
| **總費用** | **{fmt_ntd(total_sell_fee + total_sell_tax + total_buy_fee)}** |
| **口袋補差額** | **{fmt_ntd(gap)}** |
| 整數張數餘額 | {fmt_ntd(leftover_cash)} |

## 5 核心市價（v1.1 抓的）

| 代號 | 名稱 | 市價 | 來源 |
|---|---|---:|---|
{price_src_table}

## 主人下次動作

1. 看 `outputs/swap_plan_<date>_h2_v1.1.md`（主檔）
2. 去券商 App 手動下單（先賣後買，T+2 交割）
   - 買入**已是整數張數**，直接照表下單
   - 賣出**股數**用 8/19 快照（11 天前），可能 ±5~10%，下單前對一下
3. 下單完成 → 更新 `portfolio/holdings_<新日期>_h*.json`：positions 改 5 核心、刪 planned_portfolio
4. 半年後（2027-02）→ 跑 `phase6_rebalance.py`（5 核心內漂移）
""", encoding="utf-8")
    print(f"💾 決策 log：{decision_log}")
    print()
    print("=" * 70)
    print("✅ 完成")
    print("=" * 70)


if __name__ == "__main__":
    main()