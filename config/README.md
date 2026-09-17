<!--
config/ README
建立: <YYYY-MM-DD>
作者: 大寶 (agent-one)
-->

# 🔐 config/ — 專案本地設定

> **為什麼移到專案內**：原本 token 透過 symbolic link 從外部
> `<your-legacy-env-path>` 借來。
> **缺點**：換機器 / 打包轉移 / 給其他 agent 時要記得重建 symlink。
>
> **新規約**：token + 所有帳密都放這個目錄，方便 `tar` 整包帶走。

---

## 📂 檔案

| 檔案 | 是否進 git | 用途 |
|---|---|---|
| `.env.example` | ✅ | 範本（無機敏值），給未來 agent / 主人參考 |
| `.env` | ❌ gitignored | 實際 token（**僅本機**） |

---

## 🚀 一次性設定（新機器 / 重新打包時）

```bash
cd ~/.openclaw/workspace/projects/fund-plan

# 1. 從外部既有 .env 複製 token 過來
cp "<your-legacy-env-path>" \
   config/.env

# 2. 確認 FINMIND_TOKEN 有效
grep FINMIND_TOKEN config/.env

# 3. 驗證可讀（test）
python3 scripts/phase6_rebalance.py --help  # 或跑任一 phase1 phase6
```

**未來若要修改 token**（rotate / 過期換新）：
1. 到 finmindtrade.com 會員中心拿新 token
2. 編輯 `config/.env`，只改 `FINMIND_TOKEN=...` 那行
3. **不需要** 同步到外部 `.env`（新約定已切換）

---

## 🔍 Token 載入順序（`scripts/_config.py`）

新寫的 script 統一用 `scripts/_config.py`，依序嘗試：

1. **`config/.env`**（新約定，本地）← 優先
2. `<your-legacy-env-path>`（legacy，向後相容）
3. 環境變數 `FINMIND_TOKEN`（CI / container 用）

> **舊的 phase1~5 scripts 仍硬編碼 legacy path**（不要亂改以免壞掉）。
> 等下次大改版時一起 migrate。

---

## 🛡️ 安全性

- **永遠不要** `git add config/.env`
- **永遠不要** 把 token 貼進 Telegram / commit message / 報告
- 若不小心 commit → 立刻到 finmindtrade.com rotate token
- 上傳到雲端硬碟（cloud drive / Dropbox）時，`config/.env` 應在加密容器或排除清單

---

## 🔗 相關

- `portfolio/`：使用者持倉（也是機敏，每半年一份、不覆蓋）
- `.gitignore`：根目錄，保護 `config/.env` + `portfolio/*.json`