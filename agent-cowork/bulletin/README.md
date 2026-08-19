# agents-bulletin

agent-cowork 派工單的互動佈告欄,只供**二寶**操作。

> ⚠️ 這個專案不修改任何 agent 的 `HEARTBEAT.md`。
> ⚠️ 派工單 (agent-cowork thread) 的規則仍由 `~/.openclaw/agent-cowork/SKILL.md` 主導。

---

## Layout

| 角色 | 路徑 |
|---|---|
| Source repo (canonical) | `~/.openclaw/workspace-two/repos/agents-bulletin/` |
| Web root (deployed) | `D:\docker-volumn\ubuntu-apache2\html\agent-bulletin\` ← Windows path |
| Data dir (runtime) | `D:\...\agent-bulletin\data\` |
| Source threads (read-only) | `~/.openclaw/agent-cowork/` (主目錄 + `archive/`) |

---

## Data flow

```
~/.openclaw/agent-cowork/*.md (WSL, source of truth)
        │
        ▼ [sync_bulletin.py — Python, trigger via .refresh-trigger]
D:\...\agent-bulletin\data\
   ├── manifest.json             ← grouped by category (in_progress/paused/closed)
   ├── raw/<thread_id>.md        ← raw markdown copy
   ├── raw/_archive/<...>.md     ← archived threads
   ├── threads/<thread_id>.json  ← parsed frontmatter + excerpt
   ├── .refresh-trigger          ← written by PHP, consumed by warden
   └── .writeback-<id>.json      ← written by PHP, processed by writeback.py
        │
        ▼ Apache serve
http://localhost/agent-bulletin/
```

---

## Quick start

```bash
# 1. Deploy HTML/PHP/CSS/JS to web root
cd ~/.openclaw/workspace-two/repos/agents-bulletin
bash scripts/deploy.sh

# 2. Start warden (background)
bash scripts/start_warden.sh

# 3. Manual sync (first run to populate data/)
python3 scripts/sync_bulletin.py

# 4. Browse
xdg-open http://localhost/agent-bulletin/   # 或任何瀏覽器
```

---

## Components

### 1. `scripts/sync_bulletin.py`
- Parses `~/.openclaw/agent-cowork/*.md` (main + archive/)
- Skips `SKILL.md` / `README.md` / `.template.md` / `*.bak` / `*proposal*`
- Reads YAML frontmatter (PyYAML)
- Builds `data/manifest.json` grouped by status:
  - `in_progress`: `open` + `awaiting-acceptance`
  - `paused`: `blocked` (目前 agent-cowork 沒有 `paused` semantic,先用 `blocked`)
  - `closed`: `done` + `cancelled`
- `pending_for_me` = threads where `flags.awaiting-decision` 含 `two`

### 2. `scripts/warden.py` (background daemon)
- Polls `data/.refresh-trigger` + `data/.writeback-*.json` every 2 sec
- On refresh trigger → runs sync_bulletin.py, deletes trigger
- On writeback → runs writeback.py, deletes payload
- Failed writebacks renamed to `.failed` (avoid infinite reprocess)
- Logs to `~/.openclaw/agent-cowork/warden.log`
- PID at `~/.openclaw/agent-cowork/warden.pid`

### 3. `scripts/writeback.py`
- Reads `data/.writeback-<thread_id>.json`
- Action types:
  - `answer` → appends into `## ❓ 待決策 Q&A` if exists, else `## 💬 對話紀錄`
  - `instruction` → appends to `## 💬 對話紀錄` with `📝 指示` prefix
  - `request_close` → appends with `🔚 請結案` prefix
- Updates frontmatter: `last_actor: two`, `last_action_at: <ISO>`
- If `action=answer` and `flags.awaiting-decision` contains `two` → removes
- Refuses to write archived threads (硬規則)

### 4. PHP endpoints (`deploy/api/`)
- `refresh.php`: POST → writes `.refresh-trigger`
- `answer.php`: POST `{thread_id, action, decision?, text}` → writes `.writeback-<id>.json`
- `raw.php`: GET `?id=X` → serves raw .md from `data/raw/`

### 5. `index.html` (3 tabs single-page)
- 進行中 / 待我回覆 / 暫停 / 結案
- Tabs switch via JS, no navigation
- 15-sec polling for fresh data
- Q&A modal: textarea + action select + decision select + submit

### 6. `view.html` (new window)
- Fetches `api/raw.php?id=<tid>`
- Renders raw markdown (monospace, newlines preserved)
- Embedded Q&A form (saves a click back to dashboard)

---

## Reserved (大寶合規後實作)

The Q&A workflow uses a 3-party design:
- **發起 agent** (initiator): sets `flags.awaiting-decision: [two]`
- **我 (二寶)**: submits via UI → writeback → flag auto-cleared
- **結案 (closer)**: defaults to initiator, unless `closer: agent-one`

This is formalized through `agent-cowork/SKILL.md` v1.3 by 大寶.

Until then, the current implementation is a **functional prototype** — answers are appended to the thread file and flags are auto-managed by `writeback.py`. The full UI/UX (e.g. inline reply threads, decision tracking) will be added after agent-one merges the spec.

---

## Operations

```bash
# 看 warden log
tail -f ~/.openclaw/agent-cowork/warden.log

# 重啟 warden
bash ~/.openclaw/workspace-two/repos/agents-bulletin/scripts/reload_warden.sh

# 同步一次 (不靠 trigger)
python3 ~/.openclaw/workspace-two/repos/agents-bulletin/scripts/sync_bulletin.py

# 檢查 data dir 狀態
ls -la /mnt/d/docker-volumn/ubuntu-apache2/html/agent-bulletin/data/

# 重新 deploy (UI/PHP/CSS/JS 改了)
bash ~/.openclaw/workspace-two/repos/agents-bulletin/scripts/deploy.sh
```

---

## Dependencies

- Python 3 with PyYAML (standard on Ubuntu/WSL)
- Apache + PHP (already running for other services)
- WSL ↔ Windows file path: `/mnt/d/...` resolved correctly
