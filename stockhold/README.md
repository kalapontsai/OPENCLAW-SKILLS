# stockhold/post_market_report.py

盤後報告工具，把 **stock_hold API 的持倉** 與 **yfinance 的行情** 結合，
產出 JSON 格式的盤後報告（市值、今日損益、未實現損益、價格來源等）。

- 部署位置：stock_hold API（`/api/v1/holdings`、`/api/v1/securities`）
- 行情來源：預設 [yfinance](https://github.com/ranaroussi/yfinance)；`.TW` 失敗自動退回 TWSE MIS
- 設定檔：`config.json`（deploy_url + api_token）

## 目錄

1. [安裝](#安裝)
2. [設定 config.json](#設定-configjson)
3. [執行](#執行)
4. [輸出格式](#輸出格式)
6. [排障](#排障)

## 安裝

建議用專屬 venv，避免污染系統 Python（Ubuntu/Debian 預設 PEP 668 鎖 `pip install`）：

```bash
cd /home/bt994846/.openclaw/workspace/scripts/stockhold
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

## 設定 `config.json`

從範本複製後填入 token：

```bash
cp config.json.example config.json
$EDITOR config.json   # 填 deploy_url + api_token
```

`config.json` 欄位：

| Key | 必填 | 說明 |
|---|---|---|
| `deploy_url` | ✅ | stock_hold API 根網址，例如 `https://tracker.elhomeo.com` |
| `api_token` | ✅ | 你的 X-API-Token（stock_hold → Settings → API Token 產生） |
| `output_path` | — | 預設 `./output.json` |
| `price_source` | — | `yfinance`（預設）／`twse`／`auto` |
| `history_days` | — | yfinance 回看天數，預設 `10`（涵蓋週末與國定假日） |
| `fallback_to_twse` | — | yfinance 失敗時是否回退 TWSE MIS（限 `.TW`），預設 `true` |

> ⚠️ `config.json` 含有 token，請勿 commit。已在 `.gitignore` 建議清單（見下）。

### 加入 `.gitignore`

若日後把這個目錄納入 git：

```
config.json
output.json
.venv/
__pycache__/
```

## 執行

```bash
# 基本
.venv/bin/python post_market_report.py

# 自訂輸出檔
.venv/bin/python post_market_report.py -o /tmp/today.json

# 純 stdout（不寫檔）
.venv/bin/python post_market_report.py --no-write --pretty

# 強制走 TWSE MIS（跳過 yfinance，限台股）
.venv/bin/python post_market_report.py --source twse

# 指定另一份設定檔
.venv/bin/python post_market_report.py -c ~/private-stockhold-config.json
```

執行流程（stderr 會逐步印出）：

```
[1/5] 驗證 token @ https://tracker.elhomeo.com/api/v1/auth/me ...
      → 通過，使用者=Kala
[2/5] 抓 holdings ...
      → 8 筆
[3/5] 抓 securities ...
      → N 筆
[4/5] 抓行情 8 個 ticker（source=yfinance）...
      → 成功 8/8；失敗詳見 holdings[].errors
[5/5] 組裝報告 ...
      → 寫入 ./output.json
```

## 輸出格式

JSON envelope：

```json
{
  "report_version": "1.0",
  "generated_at": "2026-10-02T15:50:00+08:00",
  "username": "Kala",
  "deploy_url": "https://tracker.elhomeo.com",
  "as_of_date": "2026-10-02",
  "price_source_requested": "yfinance",
  "fallback_to_twse": true,
  "summary": {
    "holdings_count": 8,
    "priced_count": 8,
    "total_cost_basis": 8339048.4,
    "total_market_value": 8309496.1,
    "total_today_pnl": -27506.2,
    "total_today_pnl_pct": -0.33,
    "total_unrealized_pnl": -29552.3,
    "total_unrealized_pnl_pct": -0.35
  },
  "holdings": [
    {
      "symbol": "2330",
      "name": "台積電",
      "exchange": "TW",
      "yf_ticker": "2330.TW",
      "account_name": "台新證卷",
      "currency": "TWD",
      "qty": 1000,
      "avg_cost": 2475.0,
      "cost_basis": 2475000.0,
      "prev_close": 2510.0,
      "last_close": 2500.0,
      "today_change": -10.0,
      "today_change_pct": -0.4,
      "market_value": 2500000.0,
      "today_pnl": -10000.0,
      "unrealized_pnl": 25000.0,
      "unrealized_pnl_pct": 1.01,
      "portfolio_pct": 30.08,
      "price_source": "yfinance",
      "errors": []
    }
  ]
}
```

欄位說明：

- `qty`: **股數**（持倉數量，float）；股價 × qty = market_value
- `market_value`: 個股市值 = qty × last_close
- `portfolio_pct`: **個股佔總市值百分比** = `market_value / total_market_value × 100`，小數 2 位
  - 所有 holdings 的 `portfolio_pct` 加總 ≈ 100%（容許 round 誤差）
  - 個股 `market_value` 缺值（報價抓不到）→ `null`，不臆測
  - `total_market_value <= 0` → 全部 `null`，避免除以零
- `price_source`: `yfinance` / `twse_mis` / `twse_mis_fallback`
- `errors[]`: 此筆抓資料過程的所有警告（例如「yfinance 缺今日；改用 stock_hold current_price」）
- 任何欄位可能是 `null`（資料缺漏時不臆測）

### 為什麼 `portfolio_pct` 重要

- 配置檢查：一眼看出部位是否過度集中（某檔 > 30% 通常要檢視）
- 再平衡決策：搭配 `unrealized_pnl_pct` 看哪幾檔偏離目標權重
- 不會被算進 `total_market_value` 的 holdings（已抓到報價但價格 0）依然會出現在表上，百分比為 `null`

## 排障

### `HTTP 401 UNAUTHORIZED`

- `config.json` 的 `api_token` 過期或被撤銷 → 重新到 stock_hold → Settings → API Token 產一個
- 確認 `deploy_url` 沒有尾端斜線（已自動去除，但仍建議對齊）

### yfinance 在容器 / 沙箱裡 429

這個 sandbox 從裸 `curl https://query1.finance.yahoo.com` 會立刻被擋，但 yfinance 套件內部走 `curl_cffi` 模擬瀏覽器 UA 通常仍可通。如完全無法連：

1. `--source twse` 改成 TWSE MIS（台股限定，但穩定）
2. 或 `price_source = "auto"`（預設）讓 yfinance 失敗時自動 fallback
3. 部署在不受 Yahoo 限流的對外主機

### `ModuleNotFoundError: No module named 'yfinance'`

沒有啟用 venv。執行時請用：

```bash
.venv/bin/python post_market_report.py
```

而非系統 `python3`。

### `--break-system-packages` vs venv

如果你**不要**用 venv 而要直接 `pip install yfinance`：

```bash
pip install --user --break-system-packages yfinance
```

⚠️ 會動到系統 Python，WSL2 / 多專案環境不推薦。