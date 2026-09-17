<!--
fund-plan SKILL.md
建立: <YYYY-MM-DD>
更新: <YYYY-MM-DD>
作者: 大寶 (agent-one)
目的: 給未來 agent / agent-self-resume 一鍵跑完整 pipeline

-->

# 🎯 fund-plan SKILL

> **給 agent 的一句話**：
> 看到這份文件，就能從零重啟整個「退休 ETF 組合規劃」pipeline。
>
> **給主人的一句話**：
> 半年後打開 → `python3 scripts/rebalance_check.py` → 抄螢幕下單。
> **首次建倉**：`python3 scripts/phase6_swap.py`。

---

## ⚡ 一鍵指令

```bash
# === 主人日常 ===

# 半年 1 次 rebalance（5 核心內，互動式）
python3 scripts/rebalance_check.py

# 首次建倉（從現有個股+ETF 全數遷移至 5 核心）
python3 scripts/phase6_swap.py

# === Agent 自動跑 ===

# 完整 pipeline（phase 1-6）
python3 scripts/run_all.py

# 部分執行
python3 scripts/run_all.py phase3 phase6

# === Agent 環境重建（新機器 / 重新打包時）===

cp <your-legacy-token-path> \
   config/.env
```

---

## 🤖 Agent 自決原則（主人 hard requirement）

> **遇到問題或沒把握的決策**：
> 1. agent 自行評估、做合理的決定（不要卡住不動）
> 2. **每個 phase 結束時，在報告 / 決策 log 內清楚交代做了什麼決策、為何這樣選**
> 3. 若主人指定的 SOP 與當下狀況衝突 → **以主人 SOP 為準 + 在 log 註記衝突**

**什麼時候該自決**：
- 主人 SOP 沒寫的 edge case（ex: 「5 核心中 1 檔退場怎麼辦」）
- Token 過期 / API rate limit / 資料缺漏
- 多個合理選項（ex: 「放寬單檔門檻重跑」vs「換資料源」）

**自決範本（寫進 `logs/rebalance_decision_<ts>.md` 或 `logs/run_all_<phase>_<ts>.log`）**：

```markdown
## 決策：<情境>

- **遇到什麼**：xxx
- **為何這樣選**：xxx
- **影響**：xxx
- **替代方案**：xxx（為何不採用）
```

---

## 📋 Phase 總覽

| Phase | 名稱 | 觸發 | script | 瓶頸 |
|---|---|---|---|---|
| 1 | 抓 ETF 池 + smoke test | 首次 / 新 token | `scripts/phase1_fetch_universe.py` | 1 次 API |
| 2 | 單檔 5 指標計算 | 首次 / 新年度資料 | `scripts/phase2_calculate_metrics.py` | ~300 req（接近 FinMind 600/日上限）|
| 3 | 5yr 雙窗口暴力搜尋 | 每年 / 重大事件 | `scripts/phase3_v2_long_backtest.py` | CPU heavy |
| 4 | bear + walk-forward 驗證 | Phase 3 之後 | `scripts/phase4_v2_rebalance_bear_walkforward.py` | 30 min |
| 5 | 投影片 PDF | 主人要看 | `scripts/generate_slides_pdf.py` | 5 min |
| **6** | **半年 rebalance 建議** | **每年 2 月 + 8 月** | **`scripts/phase6_rebalance.py`** | **< 1 min** |
| **6.5** | **首次建倉全換光** | **首單 / 重大再平衡** | **`scripts/phase6_swap.py`** | **< 1 min** |

> 完整 spec：`PHASES.md` / 戰略邏輯：`STRATEGY.md` / 完整 re-launch spec：`PROMPT.md`

---

## 📂 專案結構（agent 必讀）

```
fund-plan/
├── SKILL.md                   ← 你現在看這份（agent 入口）
├── README.md                  ← 主人總綱
├── PHASES.md                  ← 5 phases 細節
├── STRATEGY.md                ← 戰略決策邏輯
├── PROMPT.md                  ← 完整 re-launch spec
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
│   ├── holdings_<date>_<h1|h2>.json  ← 每半年一份、不覆蓋
│   └── constraints.json       ← 主人設定的白/黑名單 + combo_size
│
├── scripts/
│   ├── _config.py             ← token 載入器
│   ├── phase1_fetch_universe.py
│   ├── phase1b_parse_etf_list.py
│   ├── phase2_calculate_metrics.py
│   ├── phase2_*.py            ← v4/v5/cleanup/tdcc/twse（迭代版本）
│   ├── phase3_v2_long_backtest.py
│   ├── phase4_v2_rebalance_bear_walkforward.py
│   ├── generate_slides_pdf.py
│   ├── phase6_rebalance.py    ← 5 核心內 rebalance
│   ├── phase6_swap.py         ← 首次建倉全換光
│   ├── run_all.py             ← agent 一鍵 phase 1-6
│   └── rebalance_check.py     ← 主人互動 CLI
│
├── data/
│   ├── etf_universe_raw.csv         (229 檔 universe)
│   ├── etf_universe_filtered.csv    (27 過門檻)
│   ├── price/  dividend/  tdcc/  twse/
│   └── phase3_cache/ phase3v2_cache/
│
├── outputs/                   ← 計算結果
│   ├── single_metrics_filtered.csv  (27 過門檻)
│   ├── phase3_v2_5yr_top3.md        ← 5 核心推薦來源
│   ├── phase3v2_phase4v2_comparison.md / .png
│   ├── fund_plan_recommendation_report.html  ← 主人最終報告
│   ├── rebalance_plan_<ts>.csv      ← phase 6 產出
│   ├── swap_plan_<date>_h2_v1.1.md  ← 換股計畫
│   ├── swap_plan_<date>_h2_v1.1.csv ← 換股 CSV
│   └── swap_decision_*.md           ← 換股決策 log
│
├── docs/
│   ├── rebalance_sop.md             ← 主人互動 SOP
│   ├── flask_api.md
│   ├── research_notes.md
│   └── schemas/                     ← 結構化規範
│       ├── log_schema.md            ← phase log 統一 schema
│       └── constraints_schema.md    ← constraints.json schema + agent 整合規則
│
├── memory/                    ← 每日工作日誌
└── logs/                      ← 執行 log + rebalance history
    ├── phase_logs/             ← 結構化 phase log
    ├── phase1.log / phase2.log / ... ← 歷史 log（不動）
    └── swap_decision_*.md / rebalance_history.log
```

## 🚀 Phase 6.5 — 首次建倉全換光

**觸發**：主人首次建倉 / 重大再平衡（從現有個股+ETF 遷移至 5 核心）

**前置**：
- `portfolio/holdings_<date>_<h1|h2>.json` 存在
- `planned_portfolio.status = "ready_to_swap"`
- `planned_portfolio.target_positions` 有 5 核心金額

**流程**：
1. 主人從券商 App 抄最新個股持倉 → 寫進 `portfolio/holdings_<date>_<h1|h2>.json` 的 `positions`
2. 同檔 `planned_portfolio` 設定 `target_total_value` + 5 核心 `target_positions` + `status = "ready_to_swap"`
3. 跑 `python3 scripts/phase6_swap.py`
4. 自動執行：
   - 抓 5 核心當下 ETF 市價（TWSE 即時）
   - **gap = 0**：買入預算 = 賣出淨收（從買入預算扣除手續費）
   - **整數張數**：`lots = floor(目標金額 / (市價 × 1000))`
   - 個股 0.3% / ETF 0.1% 賣出稅（自動判斷 `^00` 開頭）
5. 輸出：
   - `outputs/swap_plan_<date>_h2_v1.1.md`（主檔）
   - `outputs/swap_plan_<date>_h2_v1.1.csv`（對帳）
   - `logs/swap_decision_<date>_h2_v1.1.md`（決策 log）

**輸出格式**：
| 區塊 | 內容 |
|---|---|
| 換股前 | 每檔 × 賣出股數 × 現價 × 市值 × 手續費 × 交易稅 × 實收 |
| 換股後 | 每檔 × 張數 × 目標金額 × 成交價 × 成交金額 × 手續費 × 實付 |
| 費用合計 | 賣手續費 + 賣交易稅 + 買手續費 + 總費用 + 佔賣出部位比 |
| 現金流 | 賣出淨收 + 買入實付 + gap（口袋補 / 剩餘現金）|

**vs `rebalance_check.py` 差異**：
| | `rebalance_check.py` | `phase6_swap.py` |
|---|---|---|
| 觸發 | 半年 1 次（5 核心已建倉）| 首次 / 重大再平衡 |
| 輸入 | 互動式問每檔市值 | 讀 `portfolio/holdings_*.json` |
| 輸出 | 螢幕 + CSV | 螢幕 + CSV + markdown + decision log |
| 張數計算 | 不計算（主人手動）| TWSE 即時抓 + 整數張數 |
| gap | 不限制 | gap=0 設計 |

---

## 🔧 每個 phase 的決策說明（agent 自決檢查清單）

| Phase | 常見決策點 | 預設行為 |
|---|---|---|
| 1 | token 從哪讀？ | 優先 `config/.env` → legacy → ENV_VAR（`_config.py` 統一）|
| 1 | ETF 池過濾條件 | **2026 起 FinMind `type`=market（twse/tpex/emerging），ETF 在 `industry_category`（含 "ETF"）**；phase1 已 rename stock_id→tid, stock_name→name, industry_category→category |
| 1 | `listed_date` | 2026 起不存在 → 池會偏大（~500+），phase 2 處理 |
| 2 | 單檔門檻（CAGR>3%, MDD>-30%, 波動<25%, Sharpe>0.5, 配息>2%）| 維持 v5 → 若池 < 10 放寬到 (3%/30%/30%/0.3/1%) |
| 3 | 暴力搜尋 k 範圍 | k=3..7（k=8+ 計算量爆） |
| 3 | 多窗口驗證 | 3yr + 5yr 兩個窗口 Top 3 交集 → 最穩健 |
| 4 | walk-forward 重疊門檻 | < 60% = 過擬合警示 |
| 4 | bear scenario | worst 10 月等權重 → 仍需正報酬 |
| 4 | 產出檔案 | **只產 4 csv + summary JSON**，不產 `comparison.{md,png}`（doc/script 不一致；若要圖需另跑 visualizer）|
| 6 | target portfolio | `TARGET_PORTFOLIO` 常數（5 核心 20%）|
| 6 | threshold 容忍 | ±1 元視為「持平」 |
| 6 | 手續費 | 0.1425%（實測折扣後） |
| **6.5 (swap)** | **gap 處理** | **gap=0（買入預算 = 賣出淨收）** |
| **6.5 (swap)** | **張數計算** | **floor(目標金額 / (市價 × 1000))**（整數張數） |
| **6.5 (swap)** | **市價來源** | **TWSE 即時 → fallback 常數** |
| **6.5 (swap)** | **個股/ETF 判斷** | **`^00` 開頭 → ETF（0.1%）；否則個股（0.3%）** |
| 任何 | token 過期 | 立即停 + 升級主人（不重試無限次） |
| 任何 | FinMind 429 | sleep 60s × 3，3 次失敗升級 |
| 任何 | **FinMind HTTP 400 "Your level is register"** | **token 有效但等級不夠抓 price/dividend → graceful 跳過、改走 本地 cache 或 yfinance fallback（會被 rate limit）** |
| **phase 1 smoke** | **0050 price fetch 失敗** | **graceful 跳過、不中斷 phase 1；寫入 `phase1_summary.json` 的 `smoke_test_status` 欄位** |

---

## 🔑 Config / Portfolio 約定

### `config/.env`

- 存放 FinMind token + 所有帳密
- gitignored（永遠不要 commit）
- 新寫 script 用 `scripts/_config.py` 載入（向後相容 legacy）
- 詳細：`config/README.md`

### `portfolio/holdings_<date>_<H1|H2>.json`

**結構**：
```json
{
  "snapshot_date": "<YYYY-MM-DD>",
  "half": "H2",
  "total_value": <amount>,
  "data_source": "agent-stock outputs/.../holdings_enriched.json",
  "data_staleness_days": 11,
  "positions": { "2330": 2395000.00, ... },
  "positions_meta": { "2330": {"name": "台積電", "shares": 1000, "price_at_snapshot": 2395.0}, ... },
  "planned_portfolio": {
    "name": "fund-plan 5 核心等權重組合",
    "source": "...",
    "status": "ready_to_swap" | "pending",
    "target_total_value": <amount>,
    "swap_decision": "...",
    "target_positions": { "<ticker_A>": <amount>, ... },
    "note": "..."
  },
```

> ⚠️ **status enum 規範**（v1.1 + agent-stock fire drill feedback）：
> - `"ready_to_swap"`：明確批准執行 phase6_swap（標準）
> - `"pending"`：資料備齊、待主人批准
> - 其他值（含 `"ready_to_rebalance"`）：視同語意衝突，agent 應自決改為 `"ready_to_swap"` 或暫停升級主人
  "phase6_rebalance": { "applicability": "ready", "swap_plan_file": "..." },
  "notes": "..."
}
```

- **每半年一份、絕不覆蓋**
- 檔名格式：`holdings_<YYYY-MM-DD>_h2.json`（h1/h2 小寫，Unix toolchain 友善）
- **無 broker 欄位**（不存券商欄位）
- Phase 6.5 swap 自動讀**最新一份**
- gitignored
- 詳細：`portfolio/README.md`

---

## 🚨 失敗處理

| 狀況 | agent 動作 |
|---|---|
| `config/.env` + legacy 都不存在 | raise FileNotFoundError + 印搬家指令 |
| FinMind 402 (token 過期) | 立即停 + message 升級主人 |
| FinMind 429 (rate limit) | sleep 60s 重試 3 次，3 次失敗升級 |
| TWSE 抓價失敗 | fallback 到 `ETF_PRICES_FALLBACK` 常數 |
| TWSE + fallback 都沒 | raise + 印「請主人從券商 App 補價」|
| `portfolio/` 找不到 holdings | raise + 印建立指令（copy example.json）|
| `planned_portfolio.status != "ready_to_swap"` | raise + 印「先設定 planned_portfolio.status」|
| Phase 3 計算量爆 | 自動縮 k 範圍 + 在 log 註記 |
| Walk-forward < 60% | 不 panic，註記「中性觀察」，主人決定是否重跑 |
| 任何 phase 失敗 | `run_all.py` 立即停 + 印已成功 phase 列表 |
| 主人連 1hr 沒回應 | 不主動催 |

---

## 📅 半年 rebalance 時程

| 動作 | 日期 |
|---|---|
| 第 1 次 | 每年 **2 月第 1 個交易日** 收盤後 |
| 第 2 次 | 每年 **8 月第 1 個交易日** 收盤後 |

> 建議 Google Calendar 設「fund-plan rebalance」每年 2/5、8/5 提醒。
> **不要 cron / 不要 systemd**（半年 1 次 → 排程 99.96% 閒置；手動 SOP + CLI 才是正解）。

---

## 🧠 主人口味（agent 必讀）

- 「衝」= 不解釋、直接做（**少問多動**）
- 「為何」= 質疑選擇要正面答（不閃躲）
- 完成時要**交付物 + 路徑**，不要承諾
- 不要過度解釋無關 context（自言自語少做）
- **遇到邊界**：主人會用「我沒看到」「再想想」打斷 → 立即停、反思

---

## 🧪 已知限制（報告中必須揭露）

▸ 歷史回測結果 **不代表**未來
▸ 個股/ETF 配息政策可能變更
▸ 系統性風險（黑天鵝）過去 5 年沒發生
▸ 不考慮手續費、稅（粗估 0.1% 年化已扣）
▸ 不考慮追蹤誤差（ETF 偏離指數）
▸ 不考慮下單流動性（大單可能滑價）
▸ 5 年區間不涵蓋 2008 金融海嘯

---

## 🔗 Re-launch（給未來 agent）

```
你是一個會讀檔案的 AI 助手。
請依序讀取：
  ~/.openclaw/workspace/projects/fund-plan/SKILL.md         ← 入口（一鍵指令 + 自決原則）
  ~/.openclaw/workspace/projects/fund-plan/PHASES.md        ← 各 phase 細節
  ~/.openclaw/workspace/projects/fund-plan/STRATEGY.md      ← 戰略邏輯
  ~/.openclaw/workspace/projects/fund-plan/PROMPT.md        ← 完整 spec
然後：
  1. 跑 `python3 scripts/_config.py` 確認 token 正常
  2. 確認 `portfolio/holdings_*.json` 存在（找不到就提示主人建檔）
  3. 判斷此次觸發：首次建倉（跑 phase6_swap）/ 半年 rebalance（跑 phase6_rebalance）/ 完整 pipeline（跑 run_all）
  4. 每 phase 結束寫決策到對應 log（rebalance_decision_<ts>.md / swap_decision_<ts>.md / run_all_<phase>_<ts>.log）

不要重新跑已完成的 phase，除非主人/觸發條件明確要求。
```

---

*最後更新: <YYYY-MM-DD>*
*版本: <version>*

