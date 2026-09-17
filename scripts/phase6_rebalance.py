#!/usr/bin/env python3
"""
fund-plan Phase 6 — 半自動 rebalance 建議計算（非互動）

差異 vs scripts/rebalance_check.py：
- rebalance_check.py：互動式 CLI（主人手動輸入每檔市值）
- phase6_rebalance.py：非互動，從 portfolio/holdings_*.json 讀持倉

設計目的：
- 給 SKILL / agent 自動跑（每年 2 月 + 8 月 rebalance）
- 主人可在任何時候檢視「我的持倉離目標差多少」
- 寫出 rebalance_decision_<ts>.md，記錄「為何這樣算」（主人 hard requirement）
"""
import sys
import json
import csv
from pathlib import Path
from datetime import datetime

PROJECT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_DIR / "scripts"))

from _config import get_config_summary  # noqa: E402

PORTFOLIO_DIR = PROJECT_DIR / "portfolio"
OUT_DIR = PROJECT_DIR / "outputs"
LOG_DIR = PROJECT_DIR / "logs"

# 5 核心等權重（從 outputs/phase3_v2_5yr_top3.md 總分 752 取）
# 若 Phase 3 重跑後換了 5 核心，要同步改這裡 + outputs/phase3_v2_5yr_top3.md
TARGET_PORTFOLIO = [
    ("00690", "兆豐藍籌30",       0.20),
    ("00878", "國泰永續高股息",   0.20),
    ("00881", "國泰台灣5G",       0.20),
    ("00918", "大華優利高填息30", 0.20),
    ("00935", "野村臺灣新科技50", 0.20),
]

COST_PER_ROUND_TRIP = 0.00285  # 0.1425% × 2 (買 + 賣)


def load_latest_holdings() -> tuple[Path, dict]:
    """讀 portfolio/ 目錄下最新的 holdings_*.json"""
    files = sorted([
        f for f in PORTFOLIO_DIR.glob("holdings_*.json")
        if not f.name.endswith(".example.json")
    ])
    if not files:
        raise FileNotFoundError(
            f"❌ {PORTFOLIO_DIR}/ 找不到任何 holdings_*.json。\n"
            f"   請先複製 {PORTFOLIO_DIR}/holdings.example.json 為 "
            f"holdings_<日期>_<H1|H2>.json 並填入持倉。\n"
            f"   參考 {PORTFOLIO_DIR}/README.md"
        )
    latest = files[-1]
    return latest, json.loads(latest.read_text(encoding="utf-8"))


def main():
    started_at = datetime.now()
    print("=" * 70)
    print("⚖️  fund-plan Phase 6 — 半自動 rebalance 建議")
    print("=" * 70)

    # 1. 載入 token 狀態（記錄在報告，符合主人「交代每個 phase 決策」要求）
    cfg = get_config_summary()
    print(f"🔑 Token 來源：{', '.join(cfg['token_sources_found']) or '❌ 無'}")

    # 2. 載入持倉
    holdings_path, holdings = load_latest_holdings()
    total_value = float(holdings.get("total_value", 0))
    print(f"📂 持倉檔案：{holdings_path.name}")
    print(f"📅 記錄日期：{holdings.get('snapshot_date', 'unknown')}")
    print(f"💰 組合總市值：NT$ {total_value:,.0f}")

    positions = holdings.get("positions", {})
    if not positions:
        raise ValueError("❌ holdings 檔案內沒有 positions 欄位或為空")

    # 3. 對齊 5 核心（target），多餘標的列「其他」提醒
    print()
    print("📋 5 核心等權重目標（從 outputs/phase3_v2_5yr_top3.md 總分 752 取）：")
    for tid, name, w in TARGET_PORTFOLIO:
        print(f"   • {tid} {name}（{w*100:.0f}%）")

    rows = []
    for tid, name, target_w in TARGET_PORTFOLIO:
        cur_value = float(positions.get(tid, 0))
        target_value = total_value * target_w
        delta = target_value - cur_value
        if delta > 1:
            action = "➕ 買進"
        elif delta < -1:
            action = "➖ 賣出"
        else:
            action = "─ 持平"
        rows.append({
            "ticker": tid,
            "name": name,
            "target_weight": target_w,
            "current_value": cur_value,
            "target_value": target_value,
            "delta": delta,
            "action": action,
        })

    # 多餘持倉（不在 5 核心）
    target_tids = {t[0] for t in TARGET_PORTFOLIO}
    extras = [(tid, float(v)) for tid, v in positions.items()
              if tid not in target_tids and float(v) > 0]

    # 4. 顯示計畫
    print()
    print("=" * 90)
    print("📋 再平衡計畫")
    print("=" * 90)
    print(f"{'代號':6s} {'名稱':12s} {'目標權重':>8s} {'目前市值':>14s} "
          f"{'目標市值':>14s} {'差額':>14s} 動作")
    print("-" * 90)

    total_turnover = 0
    for r in rows:
        delta_str = f"{r['delta']:+,.0f}" if abs(r['delta']) >= 1 else "0"
        print(f"{r['ticker']:6s} {r['name']:12s} "
              f"{r['target_weight']*100:>7.1f}% "
              f"{r['current_value']:>14,.0f} "
              f"{r['target_value']:>14,.0f} "
              f"{delta_str:>14s} {r['action']}")
        total_turnover += abs(r['delta'])

    if extras:
        print()
        print("⚠️  不在 5 核心的持倉（請主人決定處置）：")
        for tid, value in extras:
            print(f"   • {tid} 目前市值 NT$ {value:,.0f}")

    total_cost = total_turnover * COST_PER_ROUND_TRIP
    print()
    print(f"💰 預估當次換倉金額（turnover）：NT$ {total_turnover:,.0f}")
    print(f"💸 預估當次手續費（{COST_PER_ROUND_TRIP*100:.3f}%）：NT$ {total_cost:,.0f}")
    if total_value > 0:
        print(f"📈 當次成本佔組合比：{total_cost/total_value*100:.4f}%")
        print(f"📈 年化 2 次合計：{total_cost*2/total_value*100:.4f}%")

    # 5. 寫 CSV
    today_str = started_at.strftime("%Y%m%d_%H%M%S")
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = OUT_DIR / f"rebalance_plan_{today_str}.csv"
    with open(out_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow([
            "ticker", "name", "target_weight",
            "current_value", "target_value", "delta", "action",
        ])
        for r in rows:
            writer.writerow([
                r["ticker"], r["name"], f"{r['target_weight']:.2f}",
                f"{r['current_value']:.0f}", f"{r['target_value']:.0f}",
                f"{r['delta']:.0f}", r["action"],
            ])
        writer.writerow([])
        writer.writerow([
            "TOTAL", "", "1.00",
            f"{sum(r['current_value'] for r in rows):.0f}",
            f"{total_value:.0f}",
            f"{sum(r['delta'] for r in rows):.0f}",
            f"turnover={total_turnover:.0f} cost={total_cost:.0f}",
        ])
    print()
    print(f"💾 已存：{out_path}")

    # 6. 寫決策 log（給主人 / 未來自己看「為何這樣算」）
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    decision_log = LOG_DIR / f"rebalance_decision_{today_str}.md"
    target_table = "\n".join(
        f"| {tid} | {name} | {w*100:.0f}% |" for tid, name, w in TARGET_PORTFOLIO
    )
    extras_md = (
        "（無）" if not extras
        else "\n".join(f"- {tid}: NT$ {value:,.0f}" for tid, value in extras)
    )
    decision_log.write_text(f"""# Phase 6 Rebalance 決策 log

**產生時間**：{started_at.strftime("%Y-%m-%d %H:%M:%S")}
**持倉來源**：`{holdings_path.name}`
**Token 來源**：`{', '.join(cfg['token_sources_found']) or '❌ 無'}`

## 使用的目標組合

5 核心等權重 20%（從 `outputs/phase3_v2_5yr_top3.md` 總分 752 取）：

| 代號 | 名稱 | 權重 |
|---|---|---|
{target_table}

> ⚠️ **若主人已更新組合**（Phase 3 重跑後選出新的 5 核心），
> 請同步修改 `scripts/phase6_rebalance.py` 的 `TARGET_PORTFOLIO` 與
> `outputs/phase3_v2_5yr_top3.md`。

## 換倉金額

- **turnover**：NT$ {total_turnover:,.0f}
- **單次成本**（{COST_PER_ROUND_TRIP*100:.3f}%）：NT$ {total_cost:,.0f}
- **年化 2 次合計**：NT$ {total_cost*2:,.0f}

## 額外持倉提醒

{extras_md}

## 決策依據

1. **為何用 `portfolio/holdings_*.json`**：每半年一份、不覆蓋，預設 = 使用最新一份
2. **為何不重抓持倉市值**：主人券商 App 才有即時市值，無法 API 抓
3. **為何不算稅**：稅制複雜（ETF 配息稅、交易稅），請主人看券商對帳單
4. **手續費常數 0.1425%**：券商折扣後實測值（主人永達/口袋證券）
5. **±1 元容忍**：差額 < NT$ 1 視為「持平」（避免小數進位噪音）
""", encoding="utf-8")
    print(f"💾 決策 log：{decision_log}")

    print()
    print("=" * 70)
    print("⚠️  這是純計算建議，非下單指令。")
    print("   請主人於券商 App 手動執行（先賣後買，T+2 交割）。")
    print()
    print("🫖 半年後再跑一次（每年 2 月 + 8 月）")
    print("=" * 70)


if __name__ == "__main__":
    main()