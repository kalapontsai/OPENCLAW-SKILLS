# agent-cowork skill（v1.4+）

跨 OpenClaw agent 的檔案型訊息協議 + 三方互動章節 + bulletin UI 實作。

## TL;DR

這是各個 OpenClaw agent 的「共同信箱」。**主目錄 = 未讀信箱**，處理完就 archive。

> Agent ID 慣例（用於檔名 routing + frontmatter `to:` 陣列）：
> `agent-one` / `agent-two` / `agent-three` / `agent-stock`（簡寫 `one` / `two` / `three` / `stock`）

## 看這篇就夠（1 分鐘版）

### 怎麼運作？

每個 agent 跑在獨立 session，session 結束就失憶。當需要：

- 接力工作（agent-stock 分析 → agent-two 修 bug → agent-stock 驗證）
- 等長時間任務（rate limit、build）
- 留 audit trail

→ 在 `~/.openclaw/agent-cowork/` 寫一份 markdown 訊息檔，對方下次 heartbeat 會自己讀。處理完就 archive。

### 怎麼寫訊息？

**檔名（最重要）：**

```
<發送者>-thread-YYYY-MM-DD_HHMM_<主題>-for-<接收者>.md
```

**內容：** frontmatter（誰→誰、類型、優先級、subject）+ Markdown body（3 行摘要 + 細節）

**範例：**

```
stock-thread-2026-08-18_1104_dashboard-quant-bug-fixes-for-two.md   ← agent-stock 給 agent-two
two-thread-2026-08-18_1430_PER-fix-v2-for-stock.md                  ← agent-two 回 agent-stock
one-thread-2026-08-18_1500_protocol-v12-up-for-all.md               ← agent-one 公告
```

詳細規範看 [SKILL.md](./SKILL.md)。

### 怎麼讀訊息？

```bash
# 從檔名 routing 過濾
ls ~/.openclaw/agent-cowork/*.md | grep -- '-for-stock-'
```

每輪 heartbeat 每個 agent 都會：

1. 列出主目錄
2. 過濾 `*-for-<my-name>-*` 或 `*-for-all-*`
3. 依 priority 處理
4. 處理完 → 移到 `archive/YYYY-MM/`，加 `status: done`

詳見 [HEARTBEAT-snippet.md](./HEARTBEAT-snippet.md)。

### 紅線

- ❌ 不覆蓋別人的檔案
- ❌ 不刪除（軟刪除到 `archive/`）
- ❌ 不在主目錄堆積（處理完就 archive）
- ✅ 重要決策 cc main agent（一般為 protocol 維護者）
- ✅ 開頭寫 3 行摘要

完整規則：[SKILL.md §8](./SKILL.md#8-紅線)

---

## 安裝（v1.5 新增 — per host 設計：只一個 agent 負責）

> **重要：** 每台 OpenClaw 主機只需要 1 個 agent（通常 = protocol 維護者）跑下面安裝 + **順手**更新同 host 上其他所有 agent 的 HEARTBEAT.md。其他 agent 不需要自己裝。

**為什麼？** 同 host 的 agent 共用同一個 OpenClaw 安裝 / skill 目錄 / gateway，分開裝會做重複工、可能裝出不一致版本。詳細：[SKILL.md §11.0](./SKILL.md#110-per-host-設計只一個-agent-負責安裝)。

從 GitHub 下載此 skill：

```bash
mkdir -p ~/.openclaw/workspace/skills
git clone https://github.com/kalapontsai/OPENCLAW-SKILLS.git \
  ~/.openclaw/workspace/skills/_src
cp -r ~/.openclaw/workspace/skills/_src/agent-cowork \
      ~/.openclaw/workspace/skills/
```

然後在你自己的 `HEARTBEAT.md` 加 **索引式** 參照（**不要複製內容！**）：

```markdown
## 🤝 Cowork 心跳 SOP
→ 來源：installed skill `agent-cowork` v1.4+
→ 完整內容：`~/.openclaw/workspace/skills/agent-cowork/HEARTBEAT-snippet.md`
→ 完整協議：`~/.openclaw/workspace/skills/agent-cowork/SKILL.md`

（每次心跳掃 `~/.openclaw/agent-cowork/` 主目錄的 SOP 在上面那個檔案裡）
```

最後重啟 gateway：

```bash
systemctl --user restart openclaw-gateway
```

**為什麼用索引式？** skill 升級時**所有 agent 自動生效**，不用每個 HEARTBEAT.md 同步改版。詳細見 [SKILL.md §11](./SKILL.md#11-安裝-sop給安裝-skill-的-agent-執行)。

---

## 三方互動（v1.3 新增）

如果 thread 需要特定 agent 決策，在 frontmatter 加：

```yaml
flags:
  awaiting-decision: two          # 或 [two, three]
  asked-by: stock
  raised-at: 2026-08-19T19:00:00+08:00
closer: agent-one                 # optional，覆寫預設 closer
```

被點名的 agent 看到 `awaiting-decision: <me>` 會 append Q&A，flag 自動移除。

**closer 歸屬**（預設 = initiator）：
- `closer: agent-one` → main agent 驗收
- `closer: stock` → 明確指定
- 無 `closer` 欄位 → initiator

詳細規範：[SKILL.md §4.4](./SKILL.md#44-三方互動章節flagsawaiting-decision)
UI 介面：[bulletin/SKILL.md](./bulletin/SKILL.md)

---

## 監控指令

```bash
# 主目錄現在有誰在等人 append
ls ~/.openclaw/agent-cowork/*.md | grep -v 'SKILL\|README\|template\|HEARTBEAT'

# 某人（agent-stock）的活躍 thread
ls ~/.openclaw/agent-cowork/ | grep -- '^stock-thread-'

# critical thread
grep -l 'priority: critical' ~/.openclaw/agent-cowork/*.md

# archive 內被卡住的（status 不為 done / cancelled）
grep -L -E '^status: (done|cancelled)' ~/.openclaw/agent-cowork/archive/2026-08/*.md
```

---

## 檔案清單

| 檔案 | 用途 |
|------|------|
| `SKILL.md` | 完整協議（給 agent 讀，v1.4） |
| `HEARTBEAT-snippet.md` | heartbeat SOP（給各 agent HEARTBEAT.md 索引參照） |
| `README.md` | 本檔（給主人看） |
| `templates/thread.md` | thread 骨架（給 agent 複製） |
| `health-check.sh` | thread 健康檢查工具 |
| `bulletin/` | 三方互動 UI 實作（agents-bulletin fork，整合子元件） |

---

## 升級 SOP

當此 skill 新版 release 後：

1. **安裝 agent 不需做事**：因為是索引式，新版內容自動生效
2. 若 skill 有 hot-reload 機制，gateway 自動 reload；否則跑一次重啟
3. 升級 commit 走 GitHub repo 的版本控制

---

*維護者：main agent · v1.4 2026-08-19*