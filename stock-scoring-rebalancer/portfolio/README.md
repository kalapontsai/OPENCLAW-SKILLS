<!--
portfolio/ README
建立: <YYYY-MM-DD>
作者: 大寶 (agent-one)
-->

# 💼 portfolio/ — 使用者持倉紀錄

> **設計原則**：**每半年一份、絕不覆蓋**。
> 主人一年後打開時，歷史持倉完整可追。

---

## 📂 檔案命名

```
holdings_<snapshot_date>_<half>.json
```

| 欄位 | 規則 | 範例 |
|---|---|---|
| `<snapshot_date>` | ISO 8601 短日期 | `<YYYY-MM-DD>` |
| `<half>` | `H1`（1–6 月）或 `H2`（7–12 月） | `H2` |

**完整範例**：`holdings_<YYYY-MM-DD>_H2.json`（半年後跑 phase 6 用這份）

---

## 🚀 第一次設定

```bash
cd ~/.openclaw/workspace/projects/fund-plan

# 1. 從範本複製
cp portfolio/holdings.example.json portfolio/holdings_<YYYY-MM-DD>_H2.json

# 2. 編輯、填入當下券商持倉（從永達/口袋 App 抄）
$EDITOR portfolio/holdings_<YYYY-MM-DD>_H2.json
```

---

## 📋 半年 rebalance 時（每年 2 月 + 8 月）

1. 從券商 App 抄最新持倉市值
2. **新開一份**（不要覆蓋舊的）：
   ```bash
   cp portfolio/holdings.example.json portfolio/holdings_<YYYY-MM-DD>_H1.json
   # 填入 2027-01 收盤後的市值
   ```
3. 跑 phase 6：
   ```bash
   python3 scripts/phase6_rebalance.py
   ```
   → 自動讀「最新一份」holdings_*.json → 計算 rebalance → 寫 CSV

---

## 📊 JSON 結構

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
  "notes": "首次建倉（依 fund_plan_recommendation_report.html）"
}
```

| 欄位 | 必填 | 說明 |
|---|---|---|
| `snapshot_date` | ✅ | 抄帳當天 |
| `half` | ✅ | H1/H2（影響半年週期歸屬） |
| `broker` | 🟡 | 券商名（追蹤交易成本用） |
| `total_value` | ✅ | 組合總市值（含未實現損益，**不要只算成本**） |
| `positions` | ✅ | ticker → 現值市值（NT$） |
| `notes` | 🟡 | 自由註記（ex:「剛除息」「剛合併」「純現金部位」） |

> ⚠️ `positions` 只列**目前持有的**。
> 沒有的 ticker 不用列 0（phase 6 會當 0 處理 → 計算「應買進」金額）。

---

## 🔒 安全性

- `portfolio/*.json` 已被 `.gitignore` 排除
- 含**實際資金部位**（雖非個資但仍是機敏）
- 雲端同步建議加密容器（cloud drive personal vault）

---

## 🔗 相關

- `config/`：API token 等設定
- `outputs/rebalance_plan_*.csv`：phase 6 產出的買賣清單
- `docs/rebalance_sop.md`：互動式 CLI SOP（vs phase6_rebalance.py 非互動）