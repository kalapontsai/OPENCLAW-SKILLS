#!/usr/bin/env python3
"""
fund-plan 自動 pipeline（給 agent 一鍵跑完 phase 1-6）

vs 主人手動 SOP：
- 主人：每 phase 一個指令（依 PHASES.md），逐步控制
- agent（這個腳本）：依序跑 phase 1 → 2 → 3 → 4 → 5 → 6

設計原則：
- 失敗：立即停 + log（不默默跳過）
- 部分執行：可指定 phase 名稱（白名單）→ 例：`python3 scripts/run_all.py phase3 phase5`
- 報告：每 phase 結束印 stdout 摘要（agent 可讀）

⚠️ 注意：phase 1-5 大多是單機 script（用 legacy hardcoded path 讀 .env），
   仍可正常跑。Phase 6 用新的 _config.py。
   下次大改版時統一 migrate 到 config/.env。
"""
import sys
import subprocess
from pathlib import Path
from datetime import datetime

PROJECT_DIR = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = PROJECT_DIR / "scripts"
LOG_DIR = PROJECT_DIR / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)


# (phase 名, script 路徑, 簡短描述)
PHASES = [
    ("phase1", "scripts/phase1_fetch_universe.py",                  "抓 FinMind ETF 池 + 0050 smoke test"),
    ("phase2", "scripts/phase2_calculate_metrics.py",              "單檔 5 指標計算 → 篩 27 過門檻"),
    ("phase3", "scripts/phase3_v2_long_backtest.py",               "5yr 雙窗口組合暴力搜尋 → Top 3"),
    ("phase4", "scripts/phase4_v2_rebalance_bear_walkforward.py",  "半年 rebalance + bear + walk-forward"),
    ("phase5", "scripts/generate_slides_pdf.py",                   "投影片 PDF（主人一年後看）"),
    ("phase6", "scripts/phase6_rebalance.py",                      "持倉 → 應買賣清單（需 portfolio/holdings_*.json）"),
]


def run_phase(name: str, script: str, desc: str) -> bool:
    """執行一個 phase；失敗回傳 False"""
    print()
    print("=" * 70)
    print(f"▶️  Phase: {name}")
    print(f"📝 {desc}")
    print(f"🔧 {script}")
    print("=" * 70)

    script_path = PROJECT_DIR / script
    if not script_path.exists():
        print(f"❌ 找不到 script：{script_path}")
        return False

    log_path = LOG_DIR / f"run_all_{name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
    try:
        result = subprocess.run(
            [sys.executable, str(script_path)],
            cwd=str(PROJECT_DIR),
            capture_output=True,
            text=True,
            timeout=7200,  # 2 hr per phase（瓶頸 phase3）
        )
        log_path.write_text(
            f"=== STDOUT ===\n{result.stdout}\n\n=== STDERR ===\n{result.stderr}\n",
            encoding="utf-8",
        )
        if result.returncode == 0:
            # 印 stdout 最後 40 行（給 agent 看摘要）
            tail = "\n".join(result.stdout.splitlines()[-40:])
            print(f"✅ {name} 完成")
            print("---- 最後 40 行 ----")
            print(tail)
            print(f"---- log：{log_path.name} ----")
            return True
        else:
            print(f"❌ {name} 失敗（exit {result.returncode}）")
            print(f"   stderr 最後 30 行：")
            for line in result.stderr.splitlines()[-30:]:
                print(f"   | {line}")
            print(f"   完整 log：{log_path}")
            return False
    except subprocess.TimeoutExpired:
        print(f"⏰ {name} 逾時（2hr）")
        return False
    except Exception as e:
        print(f"💥 {name} exception：{e}")
        return False


def main():
    started_at = datetime.now()
    print("=" * 70)
    print("🚀 fund-plan 自動 pipeline")
    print(f"⏰ 啟動：{started_at.strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 70)
    print()
    print("📋 即將執行：")
    for name, script, desc in PHASES:
        print(f"   {name}: {desc}")
    print()
    print("💡 Phase 6 需 portfolio/holdings_*.json（半年 rebalance 用）")
    print("💡 部分執行：`python3 scripts/run_all.py phase3 phase5`")
    print("💡 主人日常 SOP 仍走 `python3 scripts/rebalance_check.py`（互動）")

    # 允許指定 phase 名稱（白名單）
    args = sys.argv[1:]
    if args:
        requested = set(args)
        todo = [p for p in PHASES if p[0] in requested]
        if not todo:
            print()
            print(f"❌ 找不到指定 phase：{args}")
            print(f"   可用：{', '.join(p[0] for p in PHASES)}")
            sys.exit(1)
    else:
        todo = PHASES

    print()
    print(f"▶️  將執行 {len(todo)} 個 phase：{[p[0] for p in todo]}")
    print()

    results = []
    for name, script, desc in todo:
        ok = run_phase(name, script, desc)
        results.append((name, ok))
        if not ok:
            print()
            print(f"🛑 Pipeline 中斷於 {name}")
            print(f"   已完成：{[n for n, ok in results if ok]}")
            print(f"   失敗：{name}")
            break

    # 摘要
    print()
    print("=" * 70)
    print("📊 執行摘要")
    print("=" * 70)
    for name, ok in results:
        print(f"   {'✅' if ok else '❌'} {name}")
    elapsed = (datetime.now() - started_at).total_seconds()
    print(f"\n⏱  總耗時：{elapsed:.1f}s")

    failed = [n for n, ok in results if not ok]
    if failed:
        print(f"\n🛑 失敗 phase：{', '.join(failed)}")
        sys.exit(1)
    else:
        print(f"\n🎉 全部完成！")


if __name__ == "__main__":
    main()