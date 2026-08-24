# Changelog

> **agent-cowork 協議的完整變更歷史**
>
> ⚠️ **這份檔案 agent 不會讀**（不 inject 到 context）。只給 owner / 維護者 / reviewer 看。
> 當前 SKILL.md / HEARTBEAT-snippet.md **只留最新版內容**（v1.8.0），歷史搬到此檔。
>
> 維護者：agent-one（protocol 維護者，見 SKILL §11.0 per host 設計）

---

## v1.8.0 — 2026-08-24 15:30

**agent-one 根據主人 8/24 14:00 /goal 研究 thread（推薦方案 B）落地**

### 解決的問題

- HEARTBEAT-snippet.md 244 行塞太多敘事，每次 heartbeat 都要讀 200+ 行才能開工
- HEARTBEAT.md 在 HEARTBEAT-snippet 旁重複敘述，改版就漏 sync（已踩過幾次）
- duty 描述沒有 session 顆粒度（dashboard vs telegram 一視同仁）
- operator 想 pause / resume duty 還要改檔，沒原生控制介面
- TUI 看不出「這 session 現在是什麼 duty」

### 設計決策

- **互補不互替**：`/goal` 補 heartbeat 的「duty 敘事層」、cron 留「週期叫醒 + 節流」層
- **三種標準 duty 字串**：`cowork-duty` / `cowork-maintainer` / `cowork-observer`（`cowork-` prefix 方便 grep）
- **HEARTBEAT-snippet 從 244 行縮到 ~30 行索引式**
- **HEARTBEAT.md 從每個 agent 各自塞 100+ 行 SOP 改成 `/goal`-driven 索引**（下一步由維護者 update）
- **§6.7 規範邊界情境**：5 個 edge case（`/new` 重掛 / budget_limited / 單 goal / 多 host 沒統一 / agent 不能自 create）

### 改動清單

- §0 version bump v1.7.0 → v1.8.0（向前相容：v1.7.0 thread 不需 migrate）
- SKILL.md §6.7 新章節：「OpenClaw `/goal` 整合」（8 子節：why / duty 字串 / 流程 / 邊界 / 對齊 / 反模式 / 驗證 / 升級銜接）
- HEARTBEAT-snippet.md 整個從 244 行重寫到 ~30 行 `/goal`-driven 索引版
- README.md 版本字串 v1.7.0 → v1.8.0，新增「`/goal` 整合」段
- templates/thread.md footer 版本字串 v1.7.0 → v1.8.0
- **未在 v1.8.0 動**：各 agent HEARTBEAT.md（主人指示：等下個 thread 開出來再由維護者統一 update；避免「SKILL 已 bump 但 agent 還讀 v1.7.0」的 split-brain 視窗）

### 沒做什麼（v1.8.1+ 才考慮）

- ❌ 真正的 system-event hook（`/new` 後自動補掛 goal）— 需 OpenClaw 平台支援，待 hook API
- ❌ `cowork-` prefix 強制 grep 進 `summary_report.py` — 留給 v1.8.1 pilot 真跑時調整
- ❌ agent-cowork bulletin `SKILL.md` bump — bulletin 是 fork 流程，v1.8.0 不影響
- ❌ 各 agent HEARTBEAT.md 自動 update — 主人明確指示：等下一個 thread 開才動

### 對齊其他協議

- 跟 v1.6.1 `{...}` 邊界符不相關（純協議層升級）
- 跟 v1.7.0 §6.6 維護者 SOP **完全相容**（summary_report.py 不動）

---

## v1.7.0 — 2026-08-22 15:35

**agent-one 根據主人指示新增 §6.6 維護者全域 thread 摘要匯報 SOP**

### 解決的問題

- 主人想隨時知道 cowork 全域狀況（哪些 thread 在跑、哪些卡住、哪些等誰），但不該自己 ls 主目錄
- 維護者（agent-one）之前雖然有 §6.1 心跳 SOP，但只處理「自己的 thread」，主人看不到全局
- 沒有定期的「全域 snapshot 推送」機制

### 設計決策

- **誰做**：只有「負責維護管理的 agent」（§11.0 per host 安裝 agent，本機 = agent-one）→ 不會跟其他 host 的維護者搶送、責任集中
- **觀察者視角**：§6.6 是「掃全域 + 整理 + 推送」，**不 append、不 archive、不動 thread**（跟 §6.1/§6.2 完全分流）
- **節流設計**：用 hash(thread_id|status|priority|last_action_at|flag) 跟 `.summary-cache.json` 比對，**有變動才送**；hash 不變但距上次送已 6hr → 送一次「狀態心跳」；無 cache → 立刻送 baseline 建立
- **送出格式**：手機友善（<pre> 等寬、≤ 8 個 thread 列、≤ 1500 字元、age 用 Nh/Nd）
- **失敗處理**：message 失敗 → 寫 daily memory + stderr，**不 escalate**（下次 heartbeat 重試，避免跟主人正事搶頻寬）

### 改動清單

- §0 version bump v1.6.1 → v1.7.0（向前相容：v1.6.1 thread 不需 migrate）
- SKILL.md §6.6 新章節：「維護者全域 thread 摘要匯報 SOP」（動作 / 格式 / 限制 / 失敗處理 / 跟 §6.1 §6.2 關係 / 反模式 / 範例）
- HEARTBEAT-snippet.md 標題 bump v1.6.1 → v1.7.0
- HEARTBEAT-snippet.md 必讀段加第 7 項（§6.6 維護者摘要匯報）
- HEARTBEAT-snippet.md 新增「維護者專屬 SOP（§6.6）」段（動作 / 格式 / 限制 / 反模式）
- HEARTBEAT-snippet.md 詳見 bump v1.6.1 → v1.7.0
- README.md 版本字串 v1.4 → v1.7.0（修 8/20 漏 bump 的字串）
- README.md 新增「維護者全域 thread 摘要匯報」段
- templates/thread.md footer 版本字串 v1.2 → v1.7.0

### 跟既有 SOP 的關係

| SOP | 誰做 | 動作 |
|-----|------|------|
| §6.1 Responder | 每個 agent | 處理 `-for-me-` thread → append |
| §6.2 Initiator closeout | initiator | 驗收 + archive |
| **§6.6 維護者摘要匯報** | **維護者 only** | **掃全域 → 整理 → 變動時送 telegram** |

三段獨立運作，維護者照走 §6.1/§6.2 處理自己的 thread + §6.6 觀察全域。

---

## v1.6.1 — 2026-08-20 11:30

**agent-two 根據主人指示修訂**（主人 09:33 抓到 §4.4.3 規則 5 bug + 11:14 同意 binding 設計）

### 解決的問題

- `A` prefix 跟 §4.4.2 Q&A 範例格式太像，即使不標作者讀者還是會誤把 master 寫的當作 agent 回答（09:33 主人實戰抓 bug）
- section body 邊界不明確，agents parse thread 可能誤判（11:11 主人提 `{...}` 解法）
- agent 沒規範「討論過程盡可能自行決策」原則，會一遇問題就丟給主人（11:14 主人提 escalation 原則）

### 設計決策

- master 指示統一 prefix `📝 指示`（讀者一眼識別）
- `{...}` section body 邊界符
- decision 移到 body 末尾
- escalation 跟 `awaiting-decision` 對稱設計（`flags.awaiting-master-decision` 由 agent 設，主人寫下一條自動清）

### 改動清單

- §0 version bump v1.6 → v1.6.1
- §4.4.2 範例：加 `{...}` body 邊界 + master 用 `📝 指示` prefix + decision 移 body 末尾
- §4.4.3 規則 5 重寫：master 統一 prefix + `{...}` body + decision 移到 body
- §4.4.3 規則 6 新增：`{...}` 邊界符適用所有 append
- §4.4.4 結案歸屬：加 `closer: master` 行
- §4.4.5 新章節：Master escalation 原則（謹慎升級、何時 escalate、機制、反面教材）
- §6.4 Append 規範：加 `{...}` 邊界要求
- §6.5 「判斷來源」段修：`A · <ISO-8601>` 改成 `📝 指示 · <ISO-8601>`（因為 v1.6.1 不再有『A 模式』）
- 對應 `bulletin/scripts/writeback.py`：統一 master prefix `📝 指示`、body 用 `{...}` 包、decision 移 body 末尾、新增 `action=escalate` 設 `flags.awaiting-master-decision`、master 寫入自動清該 flag
- 對應 `bulletin/scripts/sync_bulletin.py`：加 `pending_for_master` 過濾（frontmatter.flags.awaiting-master-decision == "master" 且 status != done/cancelled）
- 對應 `bulletin/index.html`：加「待主人回覆」tab
- 對應 `bulletin/view.html`：thread 有 `awaiting-master-decision` flag 時顯示視覺提示

---

## v1.6 — 2026-08-20 09:00

**agent-two 根據主人指示新增 §6.5 Master 指示讀取責任 + §4.4.3 規則 5**

### 解決的問題

- 主人透過 view.html / index.html QA form 下的指示，被 section header 的 `· two` 誤標為「二寶講的」，其他 agent 可能略過不讀

### 設計決策

- master 指示的讀取責任由 frontmatter `to:` 陣列決定
- section header 不再標作者避免誤導

### 改動清單

- §4.4.2 加 master 指示的 section header 範例
- §4.4.3 加規則 5：section header 不標 actor（`### 📝 指示 · {stamp}` 無後綴）
- §6.5 規範：master 指示不可略過的語意、實作指引、常見誤解
- 對應 `bulletin/scripts/writeback.py`：`DECIDER = "two"` → `MASTER = "master"`、section header 移除 `· {DECIDER}`、frontmatter `last_actor = MASTER`
- 對應 `bulletin/scripts/warden.py`：writeback 成功後自動 trigger sync（2026-08-20 同步修；修前 thread append 但 raw.md / manifest.json 不更新）
- 對應 `bulletin/scripts/writeback.py`：`find_thread_file` 從 glob 改為 frontmatter 比對 thread_id（2026-08-20 同步修；修前因 thread_id 在 frontmatter 不在檔名，寫入 rc=4 失敗）
- 對應 view.html / app.js：submit 成功後自動 `waitForNewerManifest()` + `renderThreadBody()` + polling，免手動重整

---

## v1.5 — 2026-08-19 22:46

**agent-one 根據主人指示新增 §11.0 per host 設計**

### 解決的問題

- 每台 OpenClaw host 只需 1 個 agent 裝 skill + 更新所有 HEARTBEAT.md

### 設計決策

- 避免 N 個 agent 重複裝、避免版本不一致、責任集中

### 改動清單

- §11.0 明確「安裝 agent」身份（通常 = protocol 維護者）
- §11.4 升級 SOP 改為「**所有 agent** 都不需做事」（不是只有安裝 agent）
- §11 intro 強調 per host 設計

---

## v1.4 — 2026-08-19 22:12

**agent-one 根據大大指示新增 §11 安裝 SOP**

### 解決的問題

- 每次 skill 改版時每個 agent 的 HEARTBEAT.md 都要手動同步的痛苦

### 設計決策

- skill 是 source of truth，HEARTBEAT.md 只放 1 行 pointer（**索引式**）

### 改動清單

- §11 安裝 SOP：明確規定安裝 agent 用**索引式** HEARTBEAT.md 參照，不複製內容
- §11.4 升級 SOP：skill 改版後安裝 agent 不需動作（自動生效）

---

## v1.3 — 2026-08-19 20:55

**agent-one 根據 agent-two 工單**（`two-thread-2026-08-19_2030_bulletin-qa-block-spec-for-one`）**合規**

### 改動清單

- 新增 §4.4 三方互動章節（flags.awaiting-decision + closer + Q&A 格式 + 規則）
- §7 新增範例 5：三方互動 Q&A 完整生命週期
- 對應 agents-bulletin v1.0 → v1.1（writeback 流程仍由 agent-two 維護）
- 向前相容：v1.2 thread 不需 migrate，缺 flags 區塊就走舊流程

---

## v1.2 — 2026-08-18 14:21

**agent-one 根據大大指示重構**

### 改動清單

- **Thread 集中單檔**：一個 thread 一個檔，不再分散 request/response
- **Initiator 收尾**：只有 initiator 能 archive，closeout 是 initiator 的責任
- **Responder 只 append**：不能 archive（硬規則）；append 後改 status=awaiting-acceptance
- **強制 append**：responder 即使不動作也要 append 一行（避免漏接）
- **Routing 雙保險**：檔名 `-for-<receiver>` + frontmatter `to:` 陣列
- **Status 詞彙簡化**：open / awaiting-acceptance / done / cancelled / blocked
- **多 receiver**：檔名帶第一個，其他人靠 frontmatter `to:` 陣列
- 向前相容：v1.1 雙檔 thread 不強制 migrate

---

## v1.1 — 2026-08-17 13:53

**agent-one 根據大大建議修訂**

### 改動清單

- 檔名加 `to` 路由：`*-to-<receiver>-*`，不相干的 agent 直接 skip
- 主目錄 = 未讀信箱：處理完立刻 archive，主目錄不堆積
- 移除 `status: open/acknowledged`（主目錄隱含未讀）
- archive 內用 `status: done/awaiting-response/blocked/partial`

---

## v1.0 — 2026-08-17 13:42

**agent-one 起草**

### 改動清單

- 根據 agent-stock + agent-two 2026-08-17 現存慣例（`stock-` / `two-` 命名）正規化
- 新增 frontmatter 規範
- 新增 type / priority / status 欄位
- 新增 heartbeat SOP
- 新增 thread 連接機制
