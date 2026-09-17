<!--
fund-plan README
建立: 2026-08-29 12:09 GMT+8
更新: <YYYY-MM-DD>（每次發版更新）
作者: 大寶 (agent-one)
主人: <your-email>
-->

# 🎯 fund-plan — 退休 ETF 組合選器

> **一句話**：從台股 ETF 中，
> 用歷史回測找出符合「低波動、高夏普、合理 CAGR、低 MDD、高配息」
> 的 **5 核心等權重 20%** 組合，搭配 **半年 1 次 rebalance** SOP。

---

## 🚀 1 行指令（給主人用）

```bash
# 半年 1 次 rebalance（5 核心內漂移，互動式）
cd <project-root> && python3 scripts/rebalance_check.py
```

→ 螢幕跳出應買賣張數 + 寫 CSV → 主人到券商 App 手動下單。

## 🔀 從現有持倉全換光

```bash
# 一次性從現有個股+ETF 全數遷移至 5 核心
cd <project-root> && python3 scripts/phase6_swap.py
```

→ 螢幕 + Markdown + CSV + 決策 log：
- gap = 0（從買入預算扣除，不需從口袋掏）
- 整數張數（TWSE 即時抓價）
- 主人拿 md 檔去券商 App 執行

**前置**：`portfolio/holdings_<日期>_<h1|h2>.json` 存在（含 `planned_portfolio.status = "ready_to_swap"`）

---

## 🗓️ 半年 rebalance 時程

| 動作 | 日期 |
|---|---|
| 第 1 次 | 每年 **2 月第 1 個交易日** 收盤後 |
| 第 2 次 | 每年 **8 月第 1 個交易日** 收盤後 |

詳細 SOP：`docs/rebalance_sop.md`（手動，不用 cron）

---

## 🎯 進階機制

### 📋 Phase log 規劃

跑 pipeline 時自動寫結構化 log，方便主人檢視 + agent 重啟參考。

- **存檔目錄**：`logs/phase_logs/`
- **檔名格式**：`phase<N>_<YYYYMMDD>_<HHMMSS>_<topic>.md`
- **統一 7 區塊**：`📡 來源` / `📊 結果` / `✅ 連線` / `❌ 失敗` / `🔧 改善` / `🤖 自決` / `📝 備註`
- **完整 schema**：`docs/schemas/log_schema.md`

### 🎯 白名單 / 黑名單機制

主人在 `portfolio/constraints.json` 設定投資約束：

- **白名單**：強制保留的 ticker（即使 phase 3 沒選）+ 權重上下限
- **黑名單**：絕對排除的 ticker + 原因
- **combo_size**：min / max / prefer 組合大小（預設 3-7-5）
- **範例**（請依自身狀況填入）：
  - 白名單：`<ticker_A>` (10-30%) 大盤 beta / `<ticker_B>` (15-25%) 高股息防禦
  - 黑名單：`<ticker_C>` 主題偏退休
- **Agent 自動套用**：
  - phase 1：白名單 ticker 自動加入 universe、黑名單自動排除
  - phase 3：白名單 ticker 必進所有合法組合
  - phase 6：白名單 ticker 即使不在新 5 核心也保留不賣

### 📖 使用範例

```bash
# 修改白名單 / 黑名單
$EDITOR portfolio/constraints.json

# 驗證設定有效
python3 scripts/_constraints.py
# 輸出：
#   ✅ 載入 constraints.json
#   白名單：['<ticker_A>', '<ticker_B>']
#   黑名單：['<ticker_C>']
#   combo_size：min=3 max=7 prefer=5

# 跑 swap 會自動讀 constraints
python3 scripts/phase6_swap.py
# 自動保護白名單、排除黑名單
```

### ⚠️ 待辦（下個迭代）

- [ ] phase 3 script 改讀 constraints.json（目前是 hardcoded TOP9_UNION）
- [ ] k=6 vs k=5 量化比較（用現有 phase 3 資料重算）

---

## 📂 專案結構

```
fund-plan/
├── README.md                  ← 你現在看這份
├── SKILL.md                   ← Agent 入口（給未來 agent）
├── PHASES.md                  ← 各 phase 細節
├── STRATEGY.md                ← 戰略決策
├── PROMPT.md                  ← Phase 1 prompt
├── .gitignore                 ← 保護 config/.env + portfolio/*.json
│
├── config/                    ← 專案本地設定
│   ├── README.md
│   ├── .env.example           ← 範本
│   └── .env                   ← 實際 token（gitignored）
│
├── portfolio/                 ← 使用者持倉
│   ├── README.md
│   ├── holdings.example.json
│   └── holdings_<date>_<h1|h2>.json  ← 每半年一份、不覆蓋
│
├── data/                      ← 原始資料
│   ├── etf_universe_raw.csv         
│   ├── dividend/  tdcc/  twse/
│   └── phase3_cache/  phase3v2_cache/
│
├── outputs/                   ← 計算結果
│   ├── single_metrics_filtered.csv  
│   ├── phase3_v2_5yr_top3.md        
│   ├── phase4_v2_walkforward.csv   
│   ├── phase4_v2_bear_scenario.csv 
│   ├── phase4_v2_rebalance_compare.csv
│   ├── phase4_v2_bear_sensitivity.csv
│   ├── fund_plan_recommendation_report.html  ← 主人最終報告
│   ├── rebalance_plan_YYYYMMDD_HHMMSS.csv    ← rebalance CSV
│   ├── swap_plan_<date>_h2_v1.1.md  ← 換股計畫
│   ├── swap_plan_<date>_h2_v1.1.csv ← 換股 CSV
│   └── swap_decision_*.md           ← 換股決策 log
│
├── scripts/                   ← Python 執行
│   ├── _config.py                     ← token 載入器
│   ├── phase1_fetch_universe.py
│   ├── phase2_calculate_metrics.py
│   ├── phase3_v2_long_backtest.py
│   ├── phase4_v2_rebalance_bear_walkforward.py
│   ├── generate_slides_pdf.py
│   ├── rebalance_check.py             ← ⭐ 主人半年用（互動）
│   ├── phase6_rebalance.py            ← 5 核心內 rebalance
│   └── phase6_swap.py                 ← ⭐ 首單用（全換光）
│
├── docs/                      ← 文件
│   ├── flask_api.md
│   ├── research_notes.md
│   └── rebalance_sop.md               ← ⭐ 手動 SOP
│
├── memory/                    ← 每日工作日誌
└── logs/                      ← 執行 log + rebalance history
```

---

## 🎯 主人的角色

| 何時 | 做什麼 |
|---|---|
| **首次建倉** | 第一次下單 5 核心（從現有持倉全換光）：跑 `phase6_swap.py` → 拿 md 檔去券商 App → 執行 |
| **首次 H1 rebalance** | 第一次半年 rebalance：跑 `rebalance_check.py` |
| **每半年 1 次** | 跑 `rebalance_check.py` → 手動下單 |
| **任何 ETF 出狀況** | 重跑 Phase 3 → 更新 5 核心檔 |

---

## 🛠️ 開發者：重新跑整個 pipeline

```bash
# 一鍵全跑（agent 用）
python3 scripts/run_all.py

# 或逐步
python3 scripts/phase1_fetch_universe.py         # 5 min
python3 scripts/phase2_calculate_metrics.py     # 60 min
python3 scripts/phase3_v2_long_backtest.py       # 20 min
python3 scripts/phase4_v2_rebalance_bear_walkforward.py  # 20 min

# 換股 / rebalance（主人用）
python3 scripts/phase6_swap.py                   # 一次性全換光
python3 scripts/rebalance_check.py               # 半年 rebalance
```

總共約 2 小時（瓶頸在 yfinance rate limit）。

---

## 🚨 重要聲明

> 本專案**僅為歷史回測、非投資建議**。
>
> - 過去的優異回測結果 **不代表** 未來
> - 個股/ETF 配息政策可能變更
> - 系統性風險（黑天鵝）過去 5 年沒發生
> - **建議把「投入資金」視為「5 年以上不動用」的可投資金額**
>
> 若虧損心理準備不足，請減少部位或全改被動型 ETF。

---

## 🔗 相關連結

- 🌐 HTML 報告（Apache 已部署）：`http://localhost/fund_plan_recommendation_report.html`

---

