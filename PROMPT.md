<!--
# fund-plan PROMPT（完整 spec）
用途: 未來 re-launch / 交接給其他 agent / 自己忘了再看
建立: 2026-08-29 12:09 GMT+8
更新: <YYYY-MM-DD>
-->

# 📋 fund-plan 完整 Spec

> 給未來任何接手的人（或未來的我）：
> 看到這份文件，就能從零重啟整個專案。
>
> **Agent 入口**：先讀 `SKILL.md`（含一鍵指令 + Agent 自決原則）

---

## 🎯 目標

從 FinMind 抓台股 ETF 歷史價 + 配息，
暴力搜尋 3-10 檔 ETF 組合，
找出符合下列 **5 個條件** 的最優組合：

```
1. 年化報酬 CAGR：5% ≤ x ≤ 7%
2. 最大回檔 MDD：x > -25%
3. 年化波動率：x < 20%
4. 夏普比率：x > 1.0
5. 年配息率：x > 3%
```

---

## 🧱 環境

| 項目 | 值 |
|---|---|
| 作業系統 | WSL2（Linux） |
| Python 路徑 | `<your-python-project-root>` |
| 專案路徑 | `~/.openclaw/workspace/projects/fund-plan/` |
| Flask server | `http://<your-flask-server>:<port>/`（既有，不動） |
| 資料源 | FinMind API |
| Token | `config/.env`（優先）→ `<your-legacy-env-path>`（legacy fallback）|
| 模型 | minimax-portal/MiniMax-M3（注意 rate limit） |
| **使用者持倉** | **`portfolio/holdings_<date>_<H1\|H2>.json`**（每半年一份、不覆蓋）|

---

## 📊 資料規格

### FinMind datasets

| dataset | 用途 | 欄位 |
|---|---|---|
| `TaiwanStockInfo` | 標的清單 | stock_id, stock_name, industry_category, type |
| `TaiwanStockPrice` | 歷史價 | date, stock_id, close, volume |
| `TaiwanStockDividend` | 年度配息 | stock_id, year, stock_or_cash, ... |

### 篩選邏輯

```
Step 1: 從 TaiwanStockInfo 抓所有 type=ETF 的台股 → ETF 池
Step 2: 篩 industry_category ∈ {股票型, 債券型, REITs, 高股息, 主題型}
Step 3: 上市 ≥ 3 年（2019 前已上市）
Step 4: 每檔抓 2019-01-01 ~ 2024-12-31 收盤價
Step 5: 抓年度配息 (cash dividend)
Step 6: 進入單檔指標計算
```

---

## 📐 指標公式

| 指標 | 公式 | 說明 |
|---|---|---|
| CAGR | `(P_end/P_start)^(1/n) - 1` | n = 年數 |
| MDD | `min((P_t - P_max_so_far) / P_max_so_far)` | 整段最低 |
| 波動率 | `std(daily_return) * sqrt(252)` | 年化 |
| Sharpe | `(CAGR - Rf) / 波動率` | Rf = 1%（台灣定存近似） |
| 配息率 | `sum(cash_dividend) / P_avg` | 年化配息 / 平均價 |

---

## 🔍 演算法

### Phase 2（單檔篩選）

```
對每檔 ETF:
  計算 5 指標
  必須全部滿足下列「單檔門檻」才進入組合池：
    CAGR > 3%       ← 寬鬆（組合後加權會被稀釋）
    MDD > -30%
    波動率 < 25%
    Sharpe > 0.5
    配息率 > 2%
預期：ETF 池 100+ 檔 → 篩後剩 30-50 檔
```

### Phase 3（組合暴力搜尋）

```
for k in 3..10:
    for each C(pool, k) combination:
        weights = equal weight (1/k each)
        portfolio_return = 加權平均 daily return
        計算 5 指標
        if 全部通過:
            record (combo, weights, 5指標, sharpe)
sort by sharpe DESC
output top 100 → outputs/top_combos.csv
```

**預期計算量**：
- C(40,3) = 9,880
- C(40,4) = 91,390
- C(40,5) = 658,008
- ...C(40,10) ≈ 847,660,528
- 總和 ≈ 8.5 億組 ⚠️ **太大**

**緩解策略**：
1. Phase 2 把池縮到 20-25 檔
2. 用 multiprocessing (CPU 平行)
3. 早期剪枝：CAGR / MDD / 波動率預篩
4. 限制 max k=7（先試）

---

## 📁 檔案規格

### `data/etf_universe.csv`

```csv
stock_id,stock_name,category,listed_date
0050,元大台灣50,股票型,2003-06-30
0056,元大高股息,高股息,2007-12-26
...
```

### `data/price/{stock_id}.csv`

```csv
date,close,volume
2019-01-02,78.05,5234000
...
```

### `data/dividend/{stock_id}.csv`

```csv
year,cash_dividend,stock_dividend
2019,1.0,0.0
...
```

### `outputs/single_metrics.csv`

```csv
stock_id,stock_name,cagr,mdd,vol,sharpe,div_yield
0050,元大台灣50,8.5,-22.3,15.2,0.49,3.8
...
```

### `outputs/top_combos.csv`

```csv
rank,combo,weights,cagr,mdd,vol,sharpe,div_yield
1,"<ticker_A>,<ticker_B>,<ticker_C>",0.33/0.33/0.33,<cagr>,<mdd>,<sharpe>,<score>
...
```

### `portfolio/holdings_<date>_<H1|H2>.json`（v1.0 新增）

```json
{
  "snapshot_date": "<YYYY-MM-DD>",
  "half": "H2",
  "broker": null,
  "total_value": 1000000,
  "positions": {
    "<ticker_A>": <amount>,
    "<ticker_B>": <amount>,
    "<ticker_C>": <amount>,
    "<ticker_D>": <amount>,
    "<ticker_E>": <amount>
  },
  "notes": "首次建倉"
}
```

---

## 🐍 核心 Python 套件

```python
import requests           # FinMind API
import pandas as pd       # 資料處理
import numpy as np        # 數值計算
from itertools import combinations
from multiprocessing import Pool
import matplotlib.pyplot as plt  # 圖表
```

---

## ⚙️ API 端點範例

```python
# 推薦用 _config.py 統一載入（見 scripts/_config.py）
from _config import get_finmind_token
TOKEN = get_finmind_token()

# 抓台股清單
r = requests.get(
    'https://api.finmindtrade.com/api/v4/data',
    params={
        'dataset': 'TaiwanStockInfo',
        'token': TOKEN,
    }
)
```

```python
# 抓歷史價
r = requests.get(
    'https://api.finmindtrade.com/api/v4/data',
    params={
        'dataset': 'TaiwanStockPrice',
        'stock_id': '0050',
        'start_date': '2019-01-01',
        'end_date': '2024-12-31',
        'token': TOKEN,
    }
)
```

---

## 🚦 失敗處理

| 狀況 | 動作 |
|---|---|
| HTTP 402 (token 過期) | message 升級給主人 |
| HTTP 429 (rate limit) | sleep 60s 重試，3 次失敗升級 |
| 資料空 (empty) | 記 log，跳過此檔 |
| 計算 NaN | 過濾掉 |
| 組合無任何通過 | 放寬單檔門檻重跑 |
| `config/.env` 不存在 | raise + 印搬家指令（cp legacy → config/.env）|
| `portfolio/` 找不到 holdings | raise + 印建立指令（copy example.json）|

---

## 🆕 Phase 6 — 半年 rebalance 建議（v1.0 新增）

**觸發**：每年 2 月 + 8 月第 1 個交易日收盤後

**前置條件**：
- `portfolio/holdings_<date>_<H1|H2>.json` 存在（主人新開一份、半年一份）
- `outputs/phase3_v2_5yr_top3.md` 有 5 核心組合（總分 752）

**流程**：
1. 主人從券商 App 抄持倉 → 寫進新一份 holdings JSON（不覆蓋舊的）
2. 跑 `python3 scripts/phase6_rebalance.py`
3. 自動讀「最新一份」holdings + 5 核心 target → 計算差額
4. 輸出 `outputs/rebalance_plan_<ts>.csv`
5. 同步寫 `logs/rebalance_decision_<ts>.md`（每 phase 決策記錄）

**vs `rebalance_check.py`（互動式）差異**：
- `rebalance_check.py`：主人即時輸入每檔市值（無 holdings 檔案也可跑）
- `phase6_rebalance.py`：從 holdings JSON 讀（agent / 排程友善）

**目標組合來源**：
- 預設 = `scripts/phase6_rebalance.py` 內 `TARGET_PORTFOLIO` 常數
- 若 Phase 3 重跑換了 5 核心 → 同步改 `TARGET_PORTFOLIO` + `outputs/phase3_v2_5yr_top3.md`

---

## 🤖 Agent 自決原則（主人 hard requirement，v1.0 新增）

> 完整內容見 `SKILL.md` §「Agent 自決原則」。

摘要：
- **遇到 SOP 沒寫的 edge case** → 自行決定 + log 註記
- **每個 phase 結束** → 在報告 / log 內清楚交代做了什麼決策、為何這樣選
- **主人 SOP vs 當下狀況衝突** → 以主人 SOP 為準 + log 註記衝突
- **永遠不要 silent 失敗** → 失敗時必升級主人或寫 decision log

**常見自決情境**：
- Token 過期 / API rate limit / 資料缺漏
- 多個合理選項（ex: 放寬單檔門檻 vs 換資料源）
- 5 核心中 1 檔退場（從 27 過門檻白名單遞補）
- Walk-forward 重疊 < 60% 的處置（不 panic，註記中性觀察）

---

## 📝 re-launch 指令（給未來的 agent）

如果你從新對話接手，給未來 agent 的 prompt：

```
你是一個會讀檔案的 AI 助手。
請依序讀取：
  ~/.openclaw/workspace/projects/fund-plan/SKILL.md         ← 入口（一鍵指令 + 自決原則）
  ~/.openclaw/workspace/projects/fund-plan/PHASES.md        ← 各 phase 細節
  ~/.openclaw/workspace/projects/fund-plan/STRATEGY.md      ← 戰略邏輯
  ~/.openclaw/workspace/projects/fund-plan/PROMPT.md        ← 完整 spec（本檔）
然後：
  1. 跑 `python3 scripts/_config.py` 確認 token 正常
  2. 確認 `portfolio/holdings_*.json` 存在（找不到就提示主人建檔）
  3. 跑 `python3 scripts/run_all.py`（或指定 phase）
  4. 每 phase 結束寫決策到對應 log（rebalance_decision_<ts>.md / run_all_<phase>_<ts>.log）

不要重新跑已完成的 phase，除非主人/觸發條件明確要求。
```

---

*最後更新: <YYYY-MM-DD>*
*版本: v1.0（加入 Phase 6 + Agent 自決原則 + 5 核心推薦組合）*