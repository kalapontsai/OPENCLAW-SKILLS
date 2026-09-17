<!--
# fund-plan PHASES
建立: 2026-08-29 12:09 GMT+8
狀態: 各 phase 由主人下指令啟動
-->

# 🚦 Phase 拆分 + 執行 SOP

> **主人節奏**：每次下「跑 Phase N」就執行那一個 Phase，
> 不要一口氣跑完所有 Phase。

---

## 📊 全覽

| Phase | 名稱 | LLM 依� | 預估時間 |
|---|---|---|---|
| 0 | 環境與規格 | � 完成 | 5 min |
| 1 | 抓 ETF 清單 + 單檔驗證 | 🟡 報告時 | 15 min |
| 2 | 單檔 5 指標計算 | 🟢 純 Python | 30 min |
| 3 | 組合暴力搜尋 | 🟡 報告時 | 1-4 hr |
| 4 | Top N 詳細回測 + 視覺化 | 🟢 純 Python | 30 min |
| 5 | API / 文件（可選） | 🟡 | 30 min |

---

## Phase 0 — 環境與規格 ✅

**狀態**：完成（本輪已完成）

**產出**：
- ✅ README.md（總綱）
- ✅ PROMPT.md（給未來 re-launch）
- ✅ STRATEGY.md（為什麼這樣做）
- ✅ PHASES.md（本檔）
- ✅ 資料夾結構 `data/ scripts/ outputs/ tests/ logs/`

**驗證**：
- ✅ Flask server `http://<your-flask-server>:<port>/` HTTP 200
- ✅ `/api/profiles` 回傳 6 個現有名單
- ✅ `.env` 鏈結到 `5.python/finlab_tw_screener/.env`

**下一步**：等主人「跑 Phase 1」

---

## Phase 1 — 抓 ETF 清單 + 單檔驗證

**目標**：建立 ETF 候選池，驗證 token + API 流程

**指令**：
```
跑 Phase 1
```

**任務清單**：

1. 載入 `.env` 拿 FinMind token
2. 抓 `TaiwanStockInfo`，� `type=ETF` 的台股
3. 篩 `listed_date` ≤ 2019-01-01
4. 寫入 `data/etf_universe_raw.csv`
5. **單檔 smoke test**：
   - 抓 0050 收盤價（2019-01-01 ~ 2024-12-31）
   - 抓 0050 配息（2019-2024）
   - 印出「抓回幾筆」「日期範圍」「欄位」
6. **驗證 token 沒過期**：若 402 → 立即停 + 升級主人

**預期產出**：
- `data/etf_universe_raw.csv`（~150 檔）
- `data/price/0050.csv`（~1500 筆）
- `data/dividend/0050.csv`（5-6 筆）
- `logs/phase1.log`

**回報格式**：

```
Phase 1 完成 ✅

▸ ETF 池: XXX 檔
▸ 0050 收盤: XXX 筆 (YYYY-MM-DD ~ YYYY-MM-DD)
▸ 0050 配息: XXXX-XX-XX X.XX 元/股
▸ Token 狀態: ✅ 有效

下一步：跑 Phase 2（單檔指標計算）
```

**Rate limit 注意**：
- 抓清單 1 req
- 抓 0050 收盤 1 req（單次取 6 年）
- 抓 0050 配息 1 req
- 共 3 req → 遠低於 600/天上限

---

## Phase 2 — 單檔 5 指標計算

**目標**：對池中每檔 ETF 算 5 指標，篩選進入組合池

**指令**：
```
跑 Phase 2
```

**任務清單**：

1. 讀 `data/etf_universe_raw.csv`
2. 對每檔抓收盤價 + 配息（**共用快取**：先全抓，後續不重抓）
3. 計算 5 指標
4. 套單檔門檻（CAGR>3%, MDD>-30%, 波動<25%, Sharpe>0.5, 配息>2%）
5. 寫入：
   - `outputs/single_metrics_all.csv`（全部，含未通過）
   - `outputs/single_metrics_filtered.csv`（通過）
   - `data/etf_universe_filtered.csv`（進入組合池的名單）

**預期產出**：
- `data/price/{id}.csv`（每檔一份）
- `data/dividend/{id}.csv`（每檔一份）
- `outputs/single_metrics_all.csv`
- `outputs/single_metrics_filtered.csv`
- `data/etf_universe_filtered.csv`（~20-30 檔）
- `logs/phase2.log`

**回報格式**：

```
Phase 2 完成 ✅

▸ 計算 X 檔 / 通過 Y 檔
▸ 池縮減比例: X → Y (Z%)
▸ 通過池 TOP 5 (by Sharpe):
  1. 0050 — Sharpe 1.42
  2. 0056 — Sharpe 1.35
  ...

下一步：跑 Phase 3（暴力搜尋）
```

**Rate limit 注意**：
- 每檔 2 req（價 + 配息）
- 150 檔 = 300 req
- 接近單日上限 → **若失敗則分批**，隔天再跑

---

## Phase 3 — 組合暴力搜尋

**目標**：從通過池 C(n,k) 暴力搜尋，找出符合全部 5 條件的組合

**指令**：
```
跑 Phase 3
```

**任務清單**：

1. 讀 `data/etf_universe_filtered.csv`
2. 對每個 k = 3..7（先不做到 10，控制計算量）：
   - C(n, k) 全部組合
   - 等權重加權 daily return
   - 計算 5 指標
   - 全部通過 → 收錄
3. 用 `multiprocessing` 平行（CPU 數核心）
4. 寫入：
   - `outputs/top_combos.csv`（全部通過組合，依 Sharpe 排序）
   - `outputs/phase3_stats.json`（計算量統計）

**預期產出**：
- `outputs/top_combos.csv`（~10-100 組）
- `outputs/phase3_stats.json`
- `logs/phase3.log`

**回報格式**：

```
Phase 3 完成 ✅

▸ 通過池: X 檔
▸ 計算組合數: XXX,XXX
▸ 通過 5 條件組合: Y 組
▸ TOP 5 (by Sharpe):
  1. <ticker_A>,<ticker_B>,<ticker_C> — Sharpe <val> / CAGR <val>% / MDD <val>%
  ...

下一步：跑 Phase 4（Top N 詳細回測）
```

**Rate limit 注意**：
- 純 Python，**不消耗 API**
- 但會消耗主機 CPU
- **主人電腦不要做其他事**

**若無任何組合通過**：
- 放寬單檔門檻（CAGR > 2%, 波動 < 30%, 配息 > 1%）
- 或擴大 k 到 10
- 不要無限放寬 — 若 5 條件全部 ≤ 5%/≤ -35%/< 30%/> 0.3/> 1% 還沒組合，
  代表主人條件互斥（太高了），要回去跟主人討論

---

## Phase 4 — Top N 詳細回測 + 視覺化

**目標**：把 Top 5-10 組合畫成圖、產出可分享 HTML

**指令**：
```
跑 Phase 4
```

**任務清單**：

1. 讀 `outputs/top_combos.csv`
2. 對前 5 名做：
   - 詳細 equity curve
   - Drawdown curve
   - 月/年報酬熱度圖
   - 配息再投入 vs 不再投入 對比
3. 寫入：
   - `outputs/report_top5.html`（人看）
   - `outputs/equity_curves.csv`
   - `outputs/dividend_reinvest_compare.csv`

**預期產出**：
- `outputs/report_top5.html`
- `outputs/equity_curves.csv`
- `outputs/dividend_reinvest_compare.csv`
- `logs/phase4.log`

**回報格式**：

```
Phase 4 完成 ✅

▸ 產出 outputs/report_top5.html
▸ 含 5 個組合的 equity curve + drawdown + 配息再投入比較
▸ Telegram 上傳檔案連結: ...

下一步：跑 Phase 5（API / 文件）/ 完成
```

---

## Phase 5 — API / 文件（可選）

**目標**：把篩選邏輯包成可重用的 CLI 或 endpoint

**指令**：
```
跑 Phase 5
```

**任務清單**（任選）：

▸ 5a：寫 `scripts/find_fund_plan.py` CLI
  - 參數：池大小、最小 Sharpe、最小配息率
  - 輸出：CSV + HTML

▸ 5b：寫 Flask endpoint `/api/<your-endpoint>`
  - POST 接收參數
  - 回傳 Top 10 組合
  - 不破�既有 web UI

▸ 5c：寫 SKILL.md 給未來其他 agent

---

## 📋 主人執行 SOP

```
1. 看 PHASES.md 的當前「待執行」Phase
2. 下指令：「跑 Phase N」
3. 大寶執行 → 過程中不吵你
4. 收到回報 → 看產出檔案
5. 決定：
   a. 「跑 Phase N+1」繼續
   b. 「調整 X」微調策略
   c. 「停止」中斷
```

**絕對不要**：
- � 「跑所有 phase」
- ❌ 「隨便做」 — 主人要的是可解釋、可重現
- ❌ 半夜下指令（大寶會 sleep，你醒來會忘）

---

## ⚠️ 中斷 / 失敗處理

| 狀況 | 大寶動作 |
|---|---|
| Phase 中 token 過期 | 立即停 + message 升級 |
| Phase 中 FinMind 429 | sleep 60s 重試 3 次，3 次失敗升級 |
| Phase 中 Python exception | 寫 crash report + 留 log + 升級 |
| 主人連 1hr 沒回應 | 不主動催（大寶等你下指令） |

---

*最後更新: 2026-08-29 12:09*
