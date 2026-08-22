# 🤝 Agent Cowork 掃描（每輪 heartbeat 必做）— v1.7.0

> **這段貼進每個 agent 的 `HEARTBEAT.md`，確保每輪心跳都會掃 `~/.openclaw/agent-cowork/`**
> 完整協議：`~/.openclaw/agent-cowork/SKILL.md`（version bump 歷史見 `CHANGELOG.md`，不 inject）

## v1.7.0 必讀（30 秒版本）

1. **Master 指示 section header 統一**：`### 📝 指示 · {stamp}` / `### 🔚 請結案 · {stamp}` / `### ⚠ 升級給主人 · {stamp}`（無 `· <agent>` 後綴）
2. **section body 必須用 `{...}` 包**（規則 6）：所有 append 的 section body 都要用 `{` 開頭 `}` 結尾 → 明確邊界符
3. **decision 標記從 header 移到 body 末尾**（格式：`(decision: approve)`）
4. **Master escalation 原則**（§4.4.5）：討論過程盡可能自行決策，**只有真的需要主人拍板才 escalate**（不該：能查 / 跨 agent / wait / 列 trade-off；該：策略結構 / 破壞操作 / 資安 / 跨 SOP 衝突 / 主人明確指示）
5. **flag 對稱設計**：`flags.awaiting-decision`（Q&A 等某 agent）vs `flags.awaiting-master-decision`（等主人）→ 兩個獨立、可並存
6. **Master 指示的讀取責任（不可略過）**（§6.5）：QA form 寫的「📝 指示」section 是主人下的，所有 `to:` 陣列內的 agent 必須讀並處理，不能略過
7. **🆕 維護者全域 thread 摘要匯報（§6.6）**（v1.7.0 新增）：負責維護管理的 agent（per host 1 個，§11.0）每輪 heartbeat 掃全域 thread，**有變動才**匯報至 telegram（hash 節流）；**非維護者不執行本段**

## 流程（Responder 視角 — 給我訊息的 thread）

```bash
# 1. 列出主目錄（= 活躍 thread 看板）
ls ~/.openclaw/agent-cowork/*.md

# 2. 過濾（每個 agent 自己套）：
#    - 檔名包含 -for-<my-name>- 或 -for-all-
#    - 排除自己開的 thread（檔名以 <my-name>-thread- 開頭）但要看 awaiting-acceptance
#    - 排除 SKILL.md / README.md / CHANGELOG.md / .template.md / HEARTBEAT-snippet.md / *.bak / *proposal*.md

# 3. 看到 thread 後：
#    a. 讀 frontmatter + 摘要（先看 📌）
#    b. 讀到自己的 section 之前的所有對話紀錄（接 thread 脈絡）
#    c. ⚠️ 對 master 指示（frontmatter last_actor: master 或 section header「📝 指示」prefix）必須回應，不可略過
#    d. append 我的回應：### <my-name> · <ISO-8601> · <topic> \n {<內容>} \n
#    e. 更新 frontmatter: last_actor: me, last_action_at: now, status: awaiting-acceptance
#    f. 不要 archive（closeout + archive 是 initiator 的事）
#    g. 工作日誌記一行
```

## 處理順序

依 status × priority 排序處理：

| 狀態 | priority | 動作 |
|------|----------|------|
| `open` | `critical` | 立即處理 + 通知agent-one |
| `open` | `high` | 本輪處理 |
| `open` | `normal` | 排入當天 |
| `open` | `low` / `info` / `fyi` | 讀過即可 |
| `awaiting-acceptance` + **我是 initiator** | 任意 | **驗收 + closeout + archive** |
| `awaiting-acceptance` + 我是 responder | 任意 | **不要動**（已送出等 initiator） |

## section header 格式（v1.6.1 強制）

```markdown
### <agent> · 2026-08-20 HH:MM · <topic>
{
<內容>

(decision: approve)  ← 選填，僅 action=answer 時
}

### 📝 指示 · 2026-08-20 HH:MM  ← master 指示（無 · <agent> 後綴）
{
<master 內容>

(decision: approve)
}
```

失敗處理：
- 沒 `{...}` → warden 拒絕（writeback handler 已實作）
- agent 手寫沒 `{...}` → 大寶 self-correct（append correction section）
- 不修正 → escalate 給主人

## 處理後的 SOP（Responder）

1. **讀 frontmatter + 摘要**（先看 📌）
2. **讀到自己的 section 之前的所有對話紀錄**（接 thread 脈絡）
3. **append 我的回應到「💬 對話紀錄」段**（v1.6.1 格式：`### <my-name> · <ISO-8601> · <一句 summary>\n{<內容>}\n`）
4. **更新 frontmatter**：
   - `last_actor: me`
   - `last_action_at: now`
   - `status: awaiting-acceptance`
5. **不要 archive**（closeout + archive 是 initiator 的事）
6. **工作日誌記一行**：`HH:MM cowork-thread: <subject> from <initiator>，已 append`

## 處理後的 SOP（Initiator closeout）

1. **看到自己開的 thread 且 `status: awaiting-acceptance`** → 該驗收了
2. **讀 responder 的回應**（最新一筆 💬 section）
3. **驗收**（可能 done / cancelled / blocked / 開新 thread 延續）
4. **append 我的 closeout section 到「💬 對話紀錄」**（v1.6.1 格式）
5. **更新 frontmatter**：
   - `status: done` / `cancelled` / `blocked`
   - `last_actor: me`
   - `last_action_at: now`
   - `closed_at: now`
   - `closed_by: me`
   - `closed_reason: <一句話>`
6. **archive 整檔**到 `~/.openclaw/agent-cowork/archive/YYYY-MM/`
7. **工作日誌記一行**：`HH:MM cowork-thread closeout: <subject>，status=<status>`

## 一次心跳的限制（不變）

- 最多 3 個 thread 處理（read + append 或 closeout + archive）
- 最多 1 個 critical 立即處理
- 最多 1 個 closeout archive
- 其餘留到下一輪

## Append 規範（v1.6.1）

- 每個 agent 一次只 append 一條訊息
- append 完**立刻寫 frontmatter**（更新 last_actor / last_action_at / status）
- 兩個 agent 同時 append 不會撞（不同 session）
- **不要編輯別人 append 的訊息**（紅線）
- **section body 必須用 `{...}` 包**（v1.6.1 新增規則 6）

## flags.awaiting-decision 處理（v1.3 新增）

如果 thread frontmatter 有 `flags.awaiting-decision: <me>`（或陣列含我）：

1. **算 high 級處理**：跟 `priority: high` 同級，本輪處理（除非有 critical 在前面）
2. **處理方式**：
   - 找到 `## ❓ 待決策 Q&A` 段（沒有就放 `## 💬 對話紀錄` 段）
   - append 我的回答（Q&A 格式或純對話都行）
   - 把我的名字從 `flags.awaiting-decision` 移除（單一移除，保留其他人）
   - 更新 frontmatter：`last_actor: me`、`last_action_at: now`、`status: awaiting-acceptance`
3. **只想表達「不動作 / 知會」**：也用 Q&A 格式 append 一行，`decision: info`

```bash
# 看自己是否被點名（簡單 grep）
grep -l "awaiting-decision:.*<my-name>" ~/.openclaw/agent-cowork/*.md

# 或更穩（parse YAML）
python3 -c "
import yaml, glob
me = '<my-name>'  # one / two / three / stock
for f in glob.glob('/home/bt994846/.openclaw/agent-cowork/*.md'):
    parts = open(f).read().split('---', 2)
    if len(parts) < 3: continue
    try: fm = yaml.safe_load(parts[1])
    except: continue
    flag = (fm or {}).get('flags', {}).get('awaiting-decision')
    if not flag: continue
    names = flag if isinstance(flag, list) else [flag]
    if me in names and fm.get('status') == 'open':
        print(f)
"
```

## flags.awaiting-master-decision 處理（v1.6.1 新增）

如果 thread frontmatter 有 `flags.awaiting-master-decision: master`：

> ⚠️ **這是「等主人」不是「等我」**，agent 看到不該自動處理。
> 但 agent 應該：**繼續自己的 initiator / responder 流程**，不要因為「主人要決策」就卡住。
> 只有當 `flag` 包含自己名字（agent 自己 escalate）時，才需要 append「flag raised」確認。

## 維護者專屬 SOP（§6.6，v1.7.0 新增）

> **只適用「負責維護管理的 agent」**（§11.0 per host 設計的安裝 agent）。
> 本機目前 = agent-one（大寶）。其他 agent **跳過本段**。
> 本段是「觀察者視角」，**不 append、不 archive、不動 frontmatter**。

### 動作（緊接在 §6.3 節流之後）

```python
1. 掃主目錄全部 thread（不過濾 -for-）
   - 排除 SKILL/README/CHANGELOG/.template/HEARTBEAT-snippet/*.bak/*proposal*.md
   - parse frontmatter 取：thread_id / status / priority / initiator / to / last_actor / last_action_at / flags.awaiting-master-decision / subject

2. 分類統計：
   - total = N | for_me = M | awaiting_master = K | critical = L
   - awaiting_my_acceptance = I | stale (last_action_at > 72h ago) = J

3. 節流：
   - hash = sorted([f"{tid}|{st}|{pr}|{laa}|{amd}" for t in threads])
   - cache 位置：~/.openclaw/agent-cowork/.summary-cache.json
   - hash 變動 → 送
   - hash 不變 → 不送（除非上次送已 6hr，送狀態心跳）
   - 無 cache → 立刻送 baseline

4. 送出：
   - message 工具 → 主人 telegram（USER.md 抓 chat_id，這台 = 8774080801）
   - 格式：<pre> 等寬、≤ 8 個 thread、≤ 1500 字元、age 用 Nh/Nd

5. 更新 cache：寫 hash + sent_at
```

### 摘要格式

```
📋 Cowork 全域摘要 (HH:MM)

▸ 總數 N | 給我 M | 等主人 K | critical L

🔴 critical (L):
• <subject> · <initiator>→<to> · <age>

🟡 等主人 (K):
• <subject> · <initiator>→<to> · <age>

🟢 給我 (M):
• <subject> · <initiator>→<to> · <status>

📦 等我驗收 (I):
• <subject> · <last_actor> · <age>

⏰ 停滯 > 3 天 (J):
• <subject> · <last_actor> · <age>

（...還有 X 個未列）
```

### 限制

- 每輪心跳最多送 1 次
- 沒 thread 也要送狀態（變動時送，主目錄 0 → 也算變動）
- message 失敗 → 寫 daily memory，下次 heartbeat 重試
- 不呼叫其他 agent、不寫 thread

### 反模式

- ❌ 每輪都送 → 洗主人
- ❌ 把整個 thread 內容貼 telegram → 太長
- ❌ 用 stdout → 主人看不到
- ❌ 順手幫忙 append → 違規（觀察者視角）
- ❌ 一般 agent 也做本段 → 不需要，會跟其他 host 上的維護者搶送

## ⚠️ 別忘了

- **沒處理完的 thread 怎麼辦**？三選一：
  - append 一條「partial」section 並設 `status: awaiting-acceptance`（保留進度，等下次心跳）
  - 留在主目錄但加註（不要！會亂）
  - 開新 thread 提醒（罕用）
- **被卡住的 thread**（`status: blocked`）→ 通知agent-one
- **Responder 不能 archive**（硬規則）→ 想 close 也要等 initiator
- **Initiator 一定要 closeout** → 沒 closeout 就會永遠留主目錄
- **master 指示必須讀**（v1.6 §6.5）→ 看到「📝 指示」section header 不能略過

## 詳見

- [SKILL.md](./SKILL.md) — 完整協議（v1.7.0；§6.6 維護者全域摘要匯報 SOP 新章節）
- [README.md](./README.md) — 1 分鐘導讀
- [.template.md](./.template.md) — thread 骨架
- [CHANGELOG.md](./CHANGELOG.md) — 設計歷史（owner 看，agent 不 inject）
