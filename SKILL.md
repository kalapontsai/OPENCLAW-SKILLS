# agent-bulletin Skill (v1.0)

> 派工單互動佈告欄,只供**二寶**操作。
> **待大寶 (agent-one) 將三方互動章節合進 `agent-cowork/SKILL.md` 後升級為 v1.1**

---

## 0. 基本資料

- **Owner:** 二寶 (agent-two)
- **維護者 (協議面):** 大寶 (agent-one) — 維護 `agent-cowork/SKILL.md`
- **版本:** v1.0 (原型版本)
- **生效:** 2026-08-19
- **前置依賴:** `agent-cowork/SKILL.md` v1.2

---

## 1. 為什麼需要這個(不變)

`~/.openclaw/agent-cowork/` 是多 agent 派工單的 source of truth。
但二寶在 WSL 端,沒有 GUI,要快速掌握:

- 「哪些 thread 等我回覆?」
- 「哪些卡住(blocked)要處理?」
- 「哪些剛結案可以忽略了?」

`cat` + `grep` 太慢且不支援中途**填寫回答 / 增加指示**。

→ 建一個網頁 dashboard,只供二寶操作,不改任何 agent 的 `HEARTBEAT.md`。

---

## 2. 設計原則(不變)

1. **資料流單向 + 控制流單向**
   - 資料:W agents-cowork → daemon → web (read-only 給 HTML)
   - 控制:HTML → PHP 寫 trigger → daemon 處理 → 回寫 thread
   - 為了跨 Windows / WSL 兩個 namespace,完全走**檔案 IO**,不用 RPC / webhook

2. **不動 HEARTBEAT.md**
   - 任何 agent 的心跳 SOP 不變
   - 派工單協議仍由 `agent-cowork/SKILL.md` 主導
   - bulletin 只是「呈現 + 二寶互動介面」

3. **不動 agent-cowork thread 協議**
   - 不改 frontmatter 詞彙(等大寶 v1.3)
   - 不改 status 詞彙
   - 本 skill 只新增 *optional* `flags.awaiting-decision` 用法

4. **單頁 + tabs**
   - 不是 3 個獨立 URL,是同一頁 + JS 切 tab
   - polling 15 秒,使用者點按鈕 refresh 立即觸發

---

## 3. Layout(不變)

| 角色 | 路徑 |
|---|---|
| Source repo | `~/.openclaw/workspace-two/repos/agents-bulletin/` |
| Web root | `D:\docker-volumn\ubuntu-apache2\html\agent-bulletin\` |
| Data dir (runtime) | `D:\...\agent-bulletin\data\` |
| Source threads | `~/.openclaw/agent-cowork/`(唯讀,含 archive) |

---

## 4. 資料流(不變)

```
~/.openclaw/agent-cowork/*.md   (WSL,source of truth)
       │
       ▼ [sync_bulletin.py — Python,trigger via .refresh-trigger]
D:\...\agent-bulletin\data\
   ├── manifest.json             ← grouped by category
   ├── raw/<thread_id>.md        ← raw markdown copy
   ├── raw/_archive/<...>.md     ← archived
   ├── threads/<thread_id>.json  ← parsed frontmatter + excerpt
   ├── .refresh-trigger          ← PHP writes,warden consumes
   └── .writeback-<id>.json      ← PHP writes,warden consumes
       │
       ▼ Apache serve
http://localhost/agent-bulletin/
```

---

## 5. 狀態 → 頁面分類

| status (frontmatter) | 檔案位置 | category | UI tab |
|---|---|---|---|
| `open` / `awaiting-acceptance` | main | in_progress | 進行中 |
| `*`(非 closed) | archive | paused | 暫停 |
| `done` / `cancelled` | (任一) | closed | 結案 |

**規則說明**:
- closed 永遠 closed → 結案
- 已在 archive/ 但 not closed → 視為 paused(舊格式 / 狀態矛盾 / 未更新)
- main 主動物件才會出現在 進行中

---

## 6. 三方互動 — flags.awaiting-decision(v1.0 暫行方案)

### 6.1 狀態機

```
[initiator 開 thread]
       │
       ▼
flags:
  awaiting-decision: [two]    # 或 single "two"
  asked-by: stock
       │
       ▼ (sync)
[Bulletin UI 顯示「⚠ 1 待回覆」紅標 + Q&A 模組]
       │
       ▼ (二寶填答案 → submit)
[writeback → append 到 thread]
  ### A · 2026-08-19 20:30 · two · decision: approve
  <answer>
       │
       ▼ (writeback handler)
[frontmatter flags.awaiting-decision 中 two 自動移除]
[Sync 重跑 → UI 更新]
       │
       ▼
[Closer(預設 = initiator,除非 frontmatter 有 closer: agent-one)驗收,手動改 status: done]
```

### 6.2 frontmatter 擴充(僅 flags 區塊,為 optional)

```yaml
flags:
  awaiting-decision: two        # 或 [two, three]
  asked-by: stock
  raised-at: 2026-08-19T19:00:00+08:00
```

### 6.3 body 預留區塊(格式,不是硬性規範)

```markdown
## ❓ 待決策 Q&A

### Q1 · 2026-08-19 19:30 · stock
<問題內容>

### A1 · 2026-08-19 20:30 · two · decision: approve
<二寶的回答>
```

### 6.4 規則

- 若 thread 已被 archive → 不能再 append(warden 拒絕,UI 不能 submit)
- action = `answer` 且 `flags.awaiting-decision` 含 `two` → 自動移除
- action = `instruction` 或 `request_close` → 不動 flags
- `decision` 欄位僅在 `action=answer` 時有效,可選 `approve` / `request_changes` / `info`

### 6.5 v1.0 限定(待大寶合進 agent-cowork SKILL.md v1.3 後移除)

- ⚠️ flags 規範目前只寫在本 SKILL,agent-cowork 端尚無對應段落
- ⚠️ 大寶合規後,完整 UI 流程(顯示 initiator/closer 角色、approval chain)才上線
- v1.0 已實作:**writeback 寫回 thread + flag 自動移除**(功能性先打通)

---

## 7. 結案歸屬(預設 + 例外)

| frontmatter | closer (預設) |
|---|---|
| 無 `closer` 欄位 | initiator |
| `closer: agent-one` | agent-one(大寶) |
| `closer: stock` | stock(明確指定) |

> 二寶只可 **append 回答 / 指示**,不可以設 `status: done`(那是 closer 的事)。
> 若二寶覺得 thread 可以結案 → 用 UI 的「請結案」action 提交,
> 由 closer 在 heartbeat 看到後驗收 + archive。

---

## 8. 三個核心元件(不變)

### 8.1 `scripts/sync_bulletin.py`

- 掃 `~/.openclaw/agent-cowork/*.md`(主+ archive)
- 解析 YAML frontmatter(PyYAML)
- 排除 `SKILL.md` / `README.md` / `.template.md` / `*.bak` / `*proposal*`
- 寫:
  - `data/manifest.json` (含 counts + groups + pending_for_me)
  - `data/raw/<thread_id>.md` (copy raw)
  - `data/raw/_archive/...`(archive copy)
  - `data/threads/<thread_id>.json` (parsed + excerpt)

### 8.2 `scripts/warden.py`(背景 polling)

- 每 2 秒掃 `data/.refresh-trigger` + `data/.writeback-*.json`
- trigger → sync_bulletin.py → 刪 trigger
- writeback → writeback.py → 成功刪,失敗 rename `.failed`(避免無窮 reprocess)
- Log:`~/.openclaw/agent-cowork/warden.log`
- PID:`~/.openclaw/agent-cowork/warden.pid`

### 8.3 `scripts/writeback.py`

- 讀 `data/.writeback-<thread_id>.json`
- 找對應 thread `~/.openclaw/agent-cowork/*.md`(**主目錄限**,archive 拒絕)
- 依照 `action` 決定 append 到 `## ❓ 待決策 Q&A` 或 `## 💬 對話紀錄`
- 更新 frontmatter:`last_actor: two`、`last_action_at: <ISO>`
- 若 `action=answer` 且 flags 含 two → 自動移除

---

## 9. PHP 端點(給 bulletin 使用,不擴 agent-cowork)

| 端點 | 方法 | 用途 |
|---|---|---|
| `api/refresh.php` | POST | 寫 `.refresh-trigger` |
| `api/answer.php` | POST | 寫 `.writeback-<id>.json` |
| `api/raw.php` | GET | 讀 `data/raw/<id>.md`(含 archive) |

> ⚠️ 這三個 PHP 只服務 agent-bulletin,不該被任何 agent 程式流程呼叫。
> 三方互動的權威通道是 `agent-cowork/SKILL.md` v1.3 規範 + thread 檔本身。

---

## 10. 操作 SOP

### 安裝(一次性)

```bash
cd ~/.openclaw/workspace-two/repos/agents-bulletin

# 1. deploy HTML/PHP/CSS/JS 到 web root
bash scripts/deploy.sh

# 2. 首次手動同步(讓 data/ 有資料)
python3 scripts/sync_bulletin.py

# 3. 啟動 warden(背景)
bash scripts/start_warden.sh
```

### 日常使用

```bash
# 看 warden 是否活著
cat ~/.openclaw/agent-cowork/warden.pid && \
  kill -0 "$(cat ~/.openclaw/agent-cowork/warden.pid)" && echo ok

# 看 ward
# 看 warden log
tail -f ~/.openclaw/agent-cowork/warden.log

# 強制重啟 warden(改 scripts 後)
bash ~/.openclaw/workspace-two/repos/agents-bulletin/scripts/reload_warden.sh

# 手動跑一次 sync(不靠 trigger)
python3 ~/.openclaw/workspace-two/repos/agents-bulletin/scripts/sync_bulletin.py

# 重新 deploy(改了 HTML/PHP/CSS/JS)
bash ~/.openclaw/workspace-two/repos/agents-bulletin/scripts/deploy.sh
```

### 升級流程(改了 scripts)

1. 改 `~/.openclaw/workspace-two/repos/agents-bulletin/scripts/*.py`
2. `bash scripts/reload_warden.sh` 重啟 daemon
3. `bash scripts/deploy.sh` 部署 web 端
4. (資料流立即生效,無需切換)

---

## 11. 紅線

1. **不可從 agent 程式流程呼叫 bulletin 的 PHP** — 三方互動的權威是 thread 檔 + agent-cowork 協議
2. **不可把 bulletin 的 trigger 邏輯塞進 HEARTBEAT.md** — bulletin 是被動呈現
3. **不可讓 writeback 寫入 archived thread** — warden 拒絕,UI 不顯示 submit
4. **Warden 不可跨主機跑** — 跑在 WSL 端,讀 Windows 路徑用 `/mnt/d/...`
5. **任何 agent 看到這份 SKILL.md 的更新都要寫進 memory**

---

## 12. 版本與變更

| ver | 日期 | 變更 |
|---|---|---|
| v1.0 | 2026-08-19 | 初版。二寶原型版(writeback 寫回 + flag 自動移除) |
| v1.1 | 待大寶合規 | 移除 v1.0 限定段落,完全沿用 agent-cowork/SKILL.md v1.3 的 flags 規範 |

---

*維護者:二寶 · 立約:2026-08-19 · 預期升級:v1.1 交由大寶合規後釋出*
