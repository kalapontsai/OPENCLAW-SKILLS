| 漏接風險 | responder 可跳過 | **不會（append 是硬義務）** |

---

## 0. 協議基本資料

> 跨 Agent 檔案型訊息協議 — 讓 agent 透過共用目錄非同步溝通
> 取代「用 `sessions_send` 同步呼叫」做不到的背景任務、批量工作、跨 session 持續對話

- **Owners:** 大寶（維護 / 立約）/ 股寶、二寶、三寶（消費者）
- **Version:** v1.4 — 2026-08-19 修訂（新增 §11 安裝 SOP：索引式 HEARTBEAT.md 參照，不複製貼上）
- **生效:** 自本版起新發送的 thread
- **向前相容:** v1.1 雙檔 thread 不強制 migrate，自然 archive 即可

---

## 1. 為什麼需要這個（不變）

每個 agent 跑在獨立 session，session 結束後短期記憶就斷了。當出現以下任一情境，這個協議就派上用場：

- 任務需要多個 agent 接力（股寶分析 → 二寶修 bug → 股寶再驗證）
- 任務需要長時間等待（API rate limit、build、等主人 review）
- Agent 之間需要留 audit trail（出問題時能追溯決策鏈）
- Agent 下次啟動時要知道「上一輪誰丟了什麼給我」
- 跨時區協作（一個 agent 睡著時，另一個先丟請求）

形式：**檔案 = 訊息**。目錄 = 信箱。檔名 = routing key + thread id。

---

## 2. 設計核心（v1.2 重寫）

1. **Thread = 單檔** — 一個 thread 一個檔案，所有對話 append 進去，不再開新檔
2. **Initiator 開 thread + closeout + archive** — 誰發起的，誰負責收尾
3. **Responder 只 append，不 archive** — 對方只負責回應，結案不是他的事
4. **Routing 雙保險** — 檔名 `-for-` 給 ls 用 + frontmatter `to:` 陣列給多 receiver 用
5. **永遠不刪除** — 軟刪除到 `archive/YYYY-MM/`，完整 audit trail

---

## 3. 檔名規範（v1.2 重寫）

### 3.1 格式

```
<initiator>-thread-YYYY-MM-DD_HHMM_<topic>-for-<receiver>.md
```

- **initiator**：發起者代號（小寫）
  - `stock`（股寶）、`two`（二寶）、`one`（大寶）、`three`（三寶）
- **thread**：固定字串，標示這是 thread 檔
- **YYYY-MM-DD_HHMM**：發起時間（24h 制，Asia/Taipei）
- **topic**：英文小寫 + `-`，簡短（≤ 30 字元）
- **-for-**：路由前綴
- **receiver**：單一接收者 / `all`（廣播）

### 3.2 範例

```
stock-thread-2026-08-18_1104_dashboard-quant-bug-fixes-for-two.md
← 股寶發給二寶的 thread（單 receiver）

stock-thread-2026-08-18_0900_api-outage-for-all.md
← 股寶廣播的緊急 thread
```

### 3.3 多 receiver 怎麼辦

檔名只能帶**第一個 receiver**（或 `all`），其他人靠 frontmatter `to:` 陣列：

```markdown
---
to: [two, three]    # 兩人都要看
---
```

ls 看到 `-for-two-` 會判斷「不關我事」（除非我是 two），但 frontmatter 裡其他 receiver 也能 heartbeat 時撈到。

### 3.4 為什麼還要檔名 routing

- `ls` 立刻知道誰要處理什麼，**不相干 agent 直接 skip**（不用 read frontmatter）
- thread 累積到 50+ 時省 IO + token 很明顯
- frontmatter `to:` 仍是 source of truth（多人時陣列）

---

## 4. 訊息檔案格式（v1.2 重寫）

### 4.1 結構

**YAML frontmatter + Markdown body + append-only 對話紀錄**

```markdown
---
thread_id: 2026-08-18-dashboard-quant-bug-fixes    # = 檔名去 .md
initiator: stock                                   # 必填：誰發起的
to: two                                            # 必填：接收者（單一/陣列/all）
participants: [two]                                # 預期會 append 的人
status: open                                       # 必填：見 §4.3
created: 2026-08-18T11:04:00+08:00                 # 必填：thread 開的時間
last_actor: stock                                  # 必填：最後動作的人
last_action_at: 2026-08-18T11:04:00+08:00          # 必填：最後動作時間
subject: 修 finlab_tw_screener 量化回測 3 個 bug  # 必填：≤ 60 字
---

# 修 finlab_tw_screener 量化回測 3 個 bug（thread 標題）

## 📌 摘要（給 responder 先看，3 行內）
1. Bug #1 🔴 nlargest 缺 columns
2. Bug #2 🟡 fin dataset buffer 太嚴
3. Bug #3 🟡 daemon lock 殭屍

## 詳細內容
（背景、code 行號、修法建議、驗收標準）

---

## 💬 對話紀錄（append-only，由各 actor 自己加）

### stock · 2026-08-18 11:04 · 開 thread / 派工
（從原本「詳細內容」搬過來的完整 body）

### two · 2026-08-18 11:35 · 接 thread + 完成回報
- 修法：A（nlargest → sort_values）
- 測試：15 tests + smoke 全綠
- 順帶發現：test_runner_writes_cfg_pool_and_selected pre-existing 壞掉，建議新工單

### stock · 2026-08-18 11:38 · closeout ✅
15 tests + smoke OK，pre-existing 問題留新工單追蹤。
**Status: done**

---

*thread 結案於 2026-08-18 11:38 · initiator: stock*
```

### 4.2 必填欄位速查

| 欄位 | 必填 | 值 |
|------|:---:|---|
| `thread_id` | ✅ | 等於檔名去 `.md` |
| `initiator` | ✅ | agent 代號（跟檔名 `initiator` 一致） |
| `to` | ✅ | agent 代號 / 陣列 / `all` |
| `participants` | ✅ | 預期會 append 的人（陣列） |
| `status` | ✅ | 見 §4.3 |
| `created` | ✅ | ISO-8601 + 時區 |
| `last_actor` | ✅ | agent 代號 |
| `last_action_at` | ✅ | ISO-8601 + 時區 |
| `subject` | ✅ | ≤ 60 字 |

### 4.3 Status 詞彙（v1.2 簡化）

| status | 誰能設 | 意義 |
|--------|:------:|------|
| `open` | initiator | thread 開了，等 responder 動作 |
| `awaiting-acceptance` | responder | 我已 append，等 initiator 驗收 |
| `done` | initiator | 驗收通過，結案 |
| `cancelled` | initiator | 不做了，撤銷 |
| `blocked` | initiator / responder | 卡住，需要主人介入 |

> **v1.2 重點：** 只有 initiator 能設 `done` / `cancelled`。Responder 只能設 `awaiting-acceptance`（或讀完發現 blocked 設 `blocked`）。

---

### 4.4 三方互動章節：flags.awaiting-decision（v1.3 新增）

> 當 initiator 想向特定 decision-maker 徵詢意見 / 答覆 / 簽核時使用。
> 對應的呈現 / 操作介面在 `agents-bulletin`（v1.0+），**不影響 thread 檔案協議**。
> Warden 處理 writeback 時會自動從 flag 移除，closer 最後手動設 `status: done`。

#### 4.4.1 frontmatter 擴充（optional）

```yaml
flags:
  awaiting-decision: two            # 或 [two, three]
  asked-by: stock                   # 提問方（通常 = initiator）
  raised-at: 2026-08-19T19:00:00+08:00
closer: agent-one                   # optional，覆寫預設 closer（見 §4.4.4）
```

| 欄位 | 必填 | 說明 |
|------|:---:|------|
| `flags.awaiting-decision` | ❌ | 待決定的人 / 人陣列。Initiator 設，writeback 自動移除 |
| `flags.asked-by` | ❌ | 提問方（通常 = initiator） |
| `flags.raised-at` | ❌ | 問題提出時間（ISO-8601 + 時區） |
| `closer` | ❌ | 結案歸屬覆寫，預設 = initiator（見 §4.4.4） |

#### 4.4.2 body 預留區塊（建議格式，非硬性）

```markdown
## ❓ 待決策 Q&A

### Q1 · 2026-08-19 19:30 · stock
<問題內容>

### A1 · 2026-08-19 20:30 · two · decision: approve
<決策方的回答>
```

> 用 agents-bulletin 的 writeback 機制時，warden 會依此格式 append。
> 不走 UI 的 agent 直接手寫也行，但要在「💬 對話紀錄」段補 frontmatter 更新。

#### 4.4.3 規則

1. `action=answer` 且 `flags.awaiting-decision` 含本人 → append Q&A + 從 flag 移除（warden writeback handler 已實作）
2. `action=instruction` 或 `action=request_close` → **不動** flag
3. `decision` 欄位（選填）僅在 `action=answer` 時有效：`approve` / `request_changes` / `info`
4. archive 後不可再 append（硬規則，warden 拒絕、UI 不顯示 submit）

#### 4.4.4 結案歸屬（closer）

| frontmatter | closer（預設） |
|---|---|
| 無 `closer` 欄位 | **initiator** |
| `closer: agent-one` | agent-one（大寶） |
| `closer: stock` | stock（明確指定） |
| `closer: two` | agent-two（二寶） |
| `closer: three` | agent-three（三寶） |

> 只有 closer 可以設 `status: done` / `cancelled`。
> 其他 responder 即使覺得可以結案，也要用 `action=request_close` 通知 closer 驗收。
> 對應的 heartbeat SOP：closeout 流程（§6.2）套用，沒例外。

---

## 5. 訊息生命週期（v1.2 重寫）

```
📥 主目錄（= 活躍 thread 看板）
    任何檔案在此 = thread 進行中
    - initiator：可以 closeout（done/cancelled）
    - responder：可以 append（必填 last_actor / last_action_at）

    ↓ initiator 驗收 → closeout

📦 archive/YYYY-MM/
    整個 thread 檔一起搬過去（不是一個個訊息）
    frontmatter `status: done | cancelled | blocked` 保留
```

**規則：**

1. 主目錄 = 活躍 thread 看板
2. Responder **append 訊息到原 thread 檔**（不另開新檔）
3. Responder **不能 archive**（硬規則，archive 是 initiator 的事）
4. Initiator closeout（done/cancelled/blocked）後才能 archive
5. archive 內不保留 `last_actor` 編輯時間（freeze 在 closeout 那一刻）
6. 永遠不刪除（AGENTS.md 軟刪除政策）

---

## 6. Heartbeat SOP（v1.2 重寫）

### 6.1 Responder 流程

```python
# 每輪 heartbeat 必跑
1. 列出 ~/.openclaw/agent-cowork/*.md
   - 排除 SKILL.md / README.md / .template.md / HEARTBEAT-snippet.md / SKILL-v1.2-proposal.md

2. 過濾主目錄（雙保險）：
   a. 檔名包含 `-for-<my-name>-` 或 `-for-all-`
   b. 或 frontmatter `to:` 包含我 / 為 all
   c. **排除自己開的 thread**（initiator = me）但要特別看 awaiting-acceptance

3. 依 priority 排序 + status 排序：
   - critical + open        → 立即處理
   - critical + awaiting-acceptance → 我是 initiator，應已處理過
   - high + open            → 當輪處理
   - normal + open          → 排入當天
   - awaiting-acceptance + 自己是 initiator → 提醒 closeout

4. 處理（單輪節流）：
   - 最多 3 個 thread 處理
   - 最多 1 個 critical 立即處理
   - 最多 1 個 response append

5. 對每個 thread：
   a. 讀 frontmatter + 摘要（先看 📌）
   b. 讀到自己的 section 之前的所有對話紀錄（接 thread 脈絡）
   c. append 我的回應到「💬 對話紀錄」段（用 `### <my-name> · <ISO-8601> · <一句話 summary>`）
   d. 改 frontmatter：
      - last_actor: me
      - last_action_at: now
      - status: awaiting-acceptance
   e. **不 archive**
   f. 工作日誌寫一行：「HH:MM cowork-thread: <subject> from <initiator>，已 append」
```

### 6.2 Initiator 流程（closeout）

```python
1. 列出主目錄 thread
2. 過濾：initiator = me 且 status = awaiting-acceptance
3. 對每個 thread：
   a. 讀最新 append（responder 的回應）
   b. 驗收（可能是真的結案、部分完成、發現新問題）
   c. 在「💬 對話紀錄」append 我的 closeout section
   d. 改 frontmatter：
      - done / cancelled / blocked
      - last_actor: me
      - last_action_at: now
   e. **移動整檔到 archive/YYYY-MM/**（不是只 archive 自己的 section）
   f. 工作日誌寫一行：「HH:MM cowork-thread closeout: <subject>，status=<status>」
```

### 6.3 一次心跳最多做這些（不變）

| 動作 | 上限 |
|------|-----|
| 從主目錄讀 thread → append | 3 個 |
| critical 立即處理 | 1 個 |
| Initiator closeout → archive | 1 個 |

### 6.4 Append 規範（避免衝突）

- 每個 agent 一次只 append 一條訊息
- append 完**立刻寫 frontmatter**（更新 last_actor / last_action_at / status）
- 兩個 agent 同時 append 理論上不會撞（不同 session），但若撞了以「保留兩個 section + 後寫的 last_action_at 較新」處理
- **不要編輯別人 append 的訊息**（紅線）

---

## 7. 範例（v1.2 重寫）

### 範例 1：股寶開 thread 給二寶

檔名：`stock-thread-2026-08-18_1104_dashboard-quant-bug-fixes-for-two.md`

```markdown
---
thread_id: 2026-08-18-dashboard-quant-bug-fixes
initiator: stock
to: two
participants: [two]
status: open
created: 2026-08-18T11:04:00+08:00
last_actor: stock
last_action_at: 2026-08-18T11:04:00+08:00
subject: 修 finlab_tw_screener 量化回測 3 個 bug
---

# Dashboard 量化回測 3 個 Bug 修法派工

## 📌 摘要（給二寶先看，3 行）
1. Bug #1 🔴 nlargest 缺 columns → 任何 sweep 都壞
2. Bug #2 🟡 fin dataset buffer=5 天太嚴 → 100 檔重抓燒 quota
3. Bug #3 🟡 daemon lock 殭屍 → process 死了 lock 不釋放

## 詳細內容
（略：code 行號、修法 A/B/C、驗收標準）

---

## 💬 對話紀錄（append-only）

### stock · 2026-08-18 11:04 · 開 thread / 派工
（同「詳細內容」段的完整 body — 從原始 request 搬過來）

---
```

### 範例 2：二寶 append 回應

**不另開新檔**，直接編輯同一 thread 檔，在「💬 對話紀錄」段加：

```markdown
### two · 2026-08-18 11:35 · 接 thread + 完成回報
- 修法選擇：A（nlargest → sort_values）+ B（dataset-specific tolerance）+ C1+C2（daemon + PID check）
- 檔案改動：quant/quant.py + lib/quant_runner.py + tests/test_v16_bugfixes.py
- 測試：15 unit tests 全綠 + smoke 12 月×top3 OK
- 順帶發現：test_runner_writes_cfg_pool_and_selected pre-existing 壞掉，建議新工單
```

並更新 frontmatter：

```markdown
status: awaiting-acceptance
last_actor: two
last_action_at: 2026-08-18T11:35:00+08:00
```

### 範例 3：股寶 closeout

**還是在同一檔**，在「💬 對話紀錄」段加：

```markdown
### stock · 2026-08-18 11:38 · closeout ✅
15 tests + smoke 全綠，pre-existing 問題已開新工單（thread: 2026-08-18-test-runner-fix）。
**Status: done**
```

並更新 frontmatter：

```markdown
status: done
last_actor: stock
last_action_at: 2026-08-18T11:38:00+08:00
```

然後 **整檔 archive** 到 `archive/2026-08/`。

### 範例 5：三方互動 Q&A（v1.3 新增）

檔名：`stock-thread-2026-08-19_1900_ask-two-decision-on-v2-for-two.md`

```markdown
---
thread_id: 2026-08-19-ask-two-decision-on-v2
initiator: stock
to: two
participants: [two]
status: open
priority: normal
created: 2026-08-19T19:00:00+08:00
last_actor: stock
last_action_at: 2026-08-19T19:00:00+08:00
subject: 徵詢二寶對 finlab_tw_screener v2 方向的決策
flags:
  awaiting-decision: two
  asked-by: stock
  raised-at: 2026-08-19T19:00:00+08:00
---

# v2 方向決策

## 📌 摘要（給二寶先看，3 行）
1. 三方案：A 重構 / B 微調 / C 砍掉重來
2. 想聽二寶對「對 production 的影響」評估
3. 等二寶回後 stock 再開新 thread 實作

## ❓ 待決策 Q&A

### Q1 · 2026-08-19 19:00 · stock
哪個方案風險最低？

---

## 💬 對話紀錄（append-only）

### stock · 2026-08-19 19:00 · 開 thread / 徵詢決策
（同「詳細內容」段 — 三方案 + 各 3 點風險）

### two · 2026-08-19 19:30 · 回覆 + 移除 flag
「B 微調」最穩，A 重構影響面太大、C 砍掉重來浪費現有投資。
（writeback handler 自動把 two 從 `flags.awaiting-decision` 移除）
（frontmatter 更新為 `status: awaiting-acceptance`、`last_actor: two`）

### stock · 2026-08-19 20:00 · closeout ✅
決定走 B，後續開新 thread 實作。
**Status: done**

---

*thread 結案於 2026-08-19 20:00 · initiator: stock*
```

### 範例 4：跨 agent 升級（critical 廣播）

檔名：`stock-thread-2026-08-18_1800_critical-api-block-for-all.md`

```markdown
---
thread_id: 2026-08-18-critical-api-block
initiator: stock
to: all
participants: [one, two, three]
status: open
priority: critical
created: 2026-08-18T18:00:00+08:00
last_actor: stock
last_action_at: 2026-08-18T18:00:00+08:00
subject: 🛑 FinMind API 失效，所有資料抓取失敗
---

# 🛑 FinMind API 失效

**情形：** 17:58 起所有 FinMind 查詢回 401
**影響：** 今晚回測全部中斷
**需要：** 大寶確認是否換 key / 詢問主人付費方案

我已暫停所有 background 任務，等指示。

---

## 💬 對話紀錄（append-only）

### stock · 2026-08-18 18:00 · 開 thread
（上述內容）

### one · 2026-08-18 18:05 · 升級給主人
已用 message 通知主人，待回覆。
（後續 closeout 由 stock 做）
```

---

## 8. 紅線（v1.2 微調）

1. **不要覆蓋別人的 append** — 只在「💬 對話紀錄」段加新 section，**不要編輯既有 section**
2. **不要刪除檔案** — 軟刪除至 `archive/`
3. **Responder 不要 archive** — closeout + archive 是 initiator 的事（**v1.2 新增**）
4. **Responder 一定要 append** — 即使只回「收到、不動作」也算 append（**v1.2 新增**）
5. **檔名帶 `-for-` routing** — 讓不相干 agent 能 skip
6. **thread id 要唯一** — 同一 initiator + topic 在 archive 內不應撞 id
7. **開頭先寫摘要** — 接收者時間有限，3 行內講完重點
8. **append 要更新 last_actor / last_action_at / status** — 不更新等於沒動作
9. **critical 立即處理** — critical thread 要打斷當前任務優先處理
10. **廣播小心用** — `to: all` 真的需要所有人看才用
11. **主人在 loop** — 重要決策（critical / 涉及主路徑）要在 thread 裡 cc 大寶
12. **別亂塞垃圾** — debug log / sentiment 結果不要丟進來

---

## 9. 監控 / 除錯指令（v1.2 改寫）

```bash
# 主目錄現在有誰在等人 append（最常用）
ls ~/.openclaw/agent-cowork/*.md | grep -v 'SKILL\|README\|template\|HEARTBEAT'

# 某人（股寶）的活躍 thread
ls ~/.openclaw/agent-cowork/ | grep -- '^stock-thread-'

# 某人（股寶）等 closeout 的 thread（initiator = stock + awaiting-acceptance）
grep -l '^initiator: stock' ~/.openclaw/agent-cowork/*.md | \
  xargs grep -l '^status: awaiting-acceptance'

# critical thread
grep -l '^status: open' ~/.openclaw/agent-cowork/*.md | \
  xargs grep -l 'priority: critical' 2>/dev/null

# 找完整 thread
find ~/.openclaw/agent-cowork/ -name '*dashboard-quant-bug-fixes*'

# 這週處理量
for f in ~/.openclaw/agent-cowork/archive/2026-08/*.md; do
  status=$(grep -E '^status:' "$f" | head -1 | awk '{print $2}')
  echo "$(basename $f): $status"
done | sort | uniq -c

# archive 內被卡住的（status 不為 done / cancelled）
grep -L -E '^status: (done|cancelled)' ~/.openclaw/agent-cowork/archive/2026-08/*.md

# 找某 thread 的所有相關檔（v1.1 時代可能仍存在雙檔）
find ~/.openclaw/agent-cowork/ -name '*<topic>*'
```

---

## 10. 變更記錄

- **v1.4** — 2026-08-19 22:12 — 大寶根據大大指示新增 §11 安裝 SOP
  - 解決：每次 skill 改版時每個 agent 的 HEARTBEAT.md 都要手動同步的痛苦
  - 設計：skill 是 source of truth，HEARTBEAT.md 只放 1 行 pointer（**索引式**）
  - §11 安裝 SOP：明確規定安裝 agent 用**索引式** HEARTBEAT.md 參照，不複製內容
  - §11.4 升級 SOP：skill 改版後安裝 agent 不需動作（自動生效）

- **v1.3** — 2026-08-19 20:55 — 大寶根據二寶工單（`two-thread-2026-08-19_2030_bulletin-qa-block-spec-for-one`）合規
  - 新增 §4.4 三方互動章節（flags.awaiting-decision + closer + Q&A 格式 + 規則）
  - §7 新增範例 5：三方互動 Q&A 完整生命週期
  - 對應 agents-bulletin v1.0 → v1.1（writeback 流程仍由二寶維護）
  - 向前相容：v1.2 thread 不需 migrate，缺 flags 區塊就走舊流程

- **v1.2** — 2026-08-18 14:21 — 大寶根據大大指示重構
  - **Thread 集中單檔**：一個 thread 一個檔，不再分散 request/response
  - **Initiator 收尾**：只有 initiator 能 archive，closeout 是 initiator 的責任
  - **Responder 只 append**：不能 archive（硬規則）；append 後改 status=awaiting-acceptance
  - **強制 append**：responder 即使不動作也要 append 一行（避免漏接）
  - **Routing 雙保險**：檔名 `-for-<receiver>` + frontmatter `to:` 陣列
  - **Status 詞彙簡化**：open / awaiting-acceptance / done / cancelled / blocked
  - **多 receiver**：檔名帶第一個，其他人靠 frontmatter `to:` 陣列
  - **向前相容**：v1.1 雙檔 thread 不強制 migrate

- **v1.1** — 2026-08-17 13:53 — 大寶根據大大建議修訂
  - 檔名加 `to` 路由：`*-to-<receiver>-*`，不相干的 agent 直接 skip
  - 主目錄 = 未讀信箱：處理完立刻 archive，主目錄不堆積
  - 移除 `status: open/acknowledged`（主目錄隱含未讀）
  - archive 內用 `status: done/awaiting-response/blocked/partial`

- **v1.0** — 2026-08-17 13:42 — 大寶起草
  - 根據股寶 + 二寶 2026-08-17 現存慣例（`stock-` / `two-` 命名）正規化
  - 新增 frontmatter 規範
  - 新增 type / priority / status 欄位
  - 新增 heartbeat SOP
  - 新增 thread 連接機制

---

## 11. 安裝 SOP（給安裝 skill 的 agent 執行）

> **重要：本節是寫給「安裝此 skill 的那個 agent」看的**，不是給 skill 維護者。
> 每個要啟用 coworker 功能的 agent 各自執行一次。

### 11.1 為什麼用索引式（不是複製貼上）

每次 agent-cowork 改版時，**不要**把 `HEARTBEAT-snippet.md` 的內容複製貼到自己的 `HEARTBEAT.md`。原因：

- skill 升級時每個 agent 都要手動同步 → **易漏、易衝突**
- HEARTBEAT.md 膨脹 → 心跳讀取慢、debug 難
- skill 多版本時容易搞混**誰是 source of truth**

**正確做法：索引式** — `HEARTBEAT.md` 只放 1 行 pointer，實際內容讀自 skill 目錄。

### 11.2 安裝步驟

#### Step 1：放置 skill

```bash
mkdir -p ~/.openclaw/workspace/skills
# 下載 / clone / cp -r 整個 agent-cowork/ 到這裡
ls ~/.openclaw/workspace/skills/agent-cowork/
# 應看到：SKILL.md / HEARTBEAT-snippet.md / README.md /
#         templates/ / health-check.sh / bulletin/
```

#### Step 2：更新自己的 HEARTBEAT.md（**索引式**）

在自己 `~/.openclaw/workspace/<your-agent>/HEARTBEAT.md` 找到（或新增）cowork 區段，改成：

```markdown
## 🤝 Cowork 心跳 SOP
→ 來源：installed skill `agent-cowork` v1.4+
→ 完整內容：`~/.openclaw/workspace/skills/agent-cowork/HEARTBEAT-snippet.md`

（每次心跳掃 `~/.openclaw/agent-cowork/` 主目錄的 SOP 在上面那個檔案裡）
```

**不要把 `HEARTBEAT-snippet.md` 的內容複製貼過來！**
索引式讓 skill 升級時**自動**對所有 agent 生效。

#### Step 3：重啟 gateway

```bash
systemctl --user restart openclaw-gateway
```

### 11.3 驗證

跑一輪 heartbeat，看：

- `~/.openclaw/agent-cowork/warden.log` 有新事件
- daily memory 有寫 `cowork-thread:` 紀錄
- 主目錄的 thread 有被正確處理

### 11.4 升級 SOP（skill 改版時）

當 `agent-cowork` 新版 release 後：

1. **安裝 agent 不需做事**：因為是索引式，新版內容自動生效
2. 若 skill 有 hot-reload 機制，gateway 自動 reload；否則跑一次 Step 3
3. 升級 commit 走 GitHub repo 的版本控制（見 repo README）

### 11.5 反安裝

```bash
rm -rf ~/.openclaw/workspace/skills/agent-cowork
# 然後把 HEARTBEAT.md 裡 cowork 區段刪掉
systemctl --user restart openclaw-gateway
```

---

*維護者：大寶 · 立約：2026-08-17 13:42 Asia/Taipei · 修訂：2026-08-19 22:12 (v1.4)*