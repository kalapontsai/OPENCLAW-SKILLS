#!/usr/bin/env python3
"""
fund-plan 半年再平衡檢查腳本（單次執行，不排程）

使用時機：每年 2 月 + 8 月第 1 個交易日收盤後
操作：
  1. 跑此腳本 → 互動式輸入
  2. 螢幕 + CSV 顯示應買/應賣清單
  3. 主人到券商 App 手動下單（T+2 交割）

設計原則（為何不寫 cron）：
  - 半年 1 次 → 排程 99.96% 閒置
  - 無法自動下單（券商需要 OTP）
  - 月曆鬧鐘 + 文件 SOP 更實用
"""
import sys
import csv
from pathlib import Path
from datetime import datetime

# === 固定參數（主人可改）===
PORTFOLIO = [
    ("00690", "兆豐藍籌30",       0.20),
    ("00878", "國泰永續高股息",  0.20),
    ("00881", "國泰台灣5G",      0.20),
    ("00918", "大華優利高填息30", 0.20),
    ("00935", "野村臺灣新科技50", 0.20),
]

COST_PER_ROUND_TRIP = 0.00285  # 0.1425% × 2 (買 + 賣)

PROJECT_DIR = Path(__file__).resolve().parent.parent
OUT_DIR = PROJECT_DIR / "outputs"


def input_value(prompt: str) -> float:
    """互動式輸入金額"""
    while True:
        try:
            s = input(prompt).strip().replace(",", "").replace(" ", "")
            v = float(s)
            if v < 0:
                print("    ⚠️ 金額 ≥ 0，請重新輸入")
                continue
            return v
        except ValueError:
            print("    ⚠️ 請輸入數字")
        except (EOFError, KeyboardInterrupt):
            print("\n❌ 中斷（不做任何 rebalance）")
            sys.exit(1)


def main():
    print("=" * 70)
    print("⚖️  fund-plan 半年再平衡檢查")
    print("=" * 70)
    print()
    print("📋 5 核心等權重 20%：")
    for tid, name, w in PORTFOLIO:
        print(f"   • {tid} {name}（{w*100:.0f}%）")
    print()
    print("⏸  按 Ctrl+C 隨時中斷")
    print()

    # === 輸入總市值 ===
    total_value = input_value("💰 請輸入組合總市值（NT$，含未實現損益）: ")
    print(f"   → NT$ {total_value:,.0f}")
    print()

    # === 輸入每檔市值 ===
    rows = []
    for tid, name, target_weight in PORTFOLIO:
        cur_value = input_value(f"   {tid} {name:>10s}  目前市值 NT$: ")
        target_value = total_value * target_weight
        delta = target_value - cur_value
        if delta > 0:
            action = "➕ 買進"
        elif delta < 0:
            action = "➖ 賣出"
        else:
            action = "─ 持平"
        rows.append({
            "ticker": tid,
            "name": name,
            "target_weight": target_weight,
            "current_value": cur_value,
            "target_value": target_value,
            "delta": delta,
            "action": action,
        })

    # === 顯示計畫 ===
    print()
    print("=" * 90)
    print("📋 再平衡計畫")
    print("=" * 90)
    print(f"{'代號':6s} {'名稱':12s} {'目標權重':>8s} {'目前市值':>14s} "
          f"{'目標市值':>14s} {'差額':>14s} 動作")
    print("-" * 90)

    total_turnover = 0
    for r in rows:
        delta_str = f"{r['delta']:+,.0f}" if r['delta'] != 0 else "0"
        print(f"{r['ticker']:6s} {r['name']:12s} "
              f"{r['target_weight']*100:>7.1f}% "
              f"{r['current_value']:>14,.0f} "
              f"{r['target_value']:>14,.0f} "
              f"{delta_str:>14s} {r['action']}")
        total_turnover += abs(r['delta'])

    total_cost = total_turnover * COST_PER_ROUND_TRIP
    print()
    print(f"💰 預估當次換倉金額（turnover）：NT$ {total_turnover:,.0f}")
    print(f"💸 預估當次手續費（{COST_PER_ROUND_TRIP*100:.3f}%）：NT$ {total_cost:,.0f}")
    if total_value > 0:
        print(f"📈 當次成本佔組合比：{total_cost/total_value*100:.4f}%")
        print(f"📈 年化 2 次合計：{total_cost*2/total_value*100:.4f}%")
    print()

    # === 寫 CSV ===
    today_str = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = OUT_DIR / f"rebalance_plan_{today_str}.csv"
    OUT_DIR.mkdir(parents=True, exist_ok=True)

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

    print(f"💾 已存：{out_path}")
    print()
    print("=" * 70)
    print("⚠️  這是純計算建議，非下單指令。")
    print("   請主人於券商 App 手動執行（先賣後買，T+2 交割）。")
    print()
    print("🫖 半年後再跑一次（每年 2 月 + 8 月）")
    print("=" * 70)


if __name__ == "__main__":
    main()
