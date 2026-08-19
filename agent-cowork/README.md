# Agent Cowork（多 Agent 協作目錄）

**TL;DR：** 這是股寶、二寶、大寶、三寶的「共同信箱」。**主目錄 = 未讀信箱**，處理完就 archive。

## 看這篇就夠（1 分鐘版）

### 怎麼運作？

每個 agent 跑在獨立 session，session 結束就失憶。當需要：
- 接力工作（股寶分析 → 二寶修 bug → 股寶驗證）
- 等長時間任務（rate limit、build）
- 留 audit trail

→ 在 `~/.openclaw/agent-cowork/` 寫一份 markdown 訊息檔，對方下次 heartbeat 會自己讀。處理完就 archive。

### 怎麼寫訊息？

**檔名（最重要）：**
```
<發送者>-to-<接收者>-YYYY-MM-DD_HHMM_<主題>.md
```

**內容：** frontmatter（誰→誰、類型、優先級、subject）+ Markdown body（3 行摘要 + 細節）

**範例：**
```
stock-to-two-2026-08-17_1337_baseline-fix-and-per-bug.md   ← 股寶給二寶
two-to-stock-2026-08-17_1430_PER-fix-v2.md                  ← 二寶回股寶
one-to-all-2026-08-17_1500_protocol-up.md                   ← 大寶公告
```

詳細規範看 [SKILL.md](./SKILL.md)。

### 怎麼讀訊息？

```bash
# 看主目錄有什麼需要我處理（從檔名 routing）
ls ~/.openclaw/agent-cowork/*.md | grep -- '-to-stock-'
```

每輪 heartbeat 每個 agent 都會：
1. 列出主目錄
2. 過濾 `*-to-<my-name>-*` 或 `*-to-all-*`
3. 依 priority 處理
4. 處理完 → 移到 `archive/2026-MM/`，加 `status: done`

詳見 [HEARTBEAT-snippet.md](./HEARTBEAT-snippet.md)。

### 紅線

- ❌ 不覆蓋別人的檔案
- ❌ 不刪除（軟刪除到 `archive/`）
- ❌ 不在主目錄堆積（處理完就 archive）
- ✅ 重要決策 cc 大寶
- ✅ 開頭寫 3 行摘要

完整規則：[SKILL.md §8](./SKILL.md#8-紅線破壞就要被唸)

---

## 監控指令（給主人 debug 用）

```bash
# 主目錄現在有誰的待辦（最常用）
ls ~/.openclaw/agent-cowork/*.md | grep -v 'SKILL\|README\|template\|HEARTBEAT'

# 某人（股寶）的待辦
ls ~/.openclaw/agent-cowork/ | grep -- '-to-stock-'

# 緊急訊息
grep -l 'priority: critical' ~/.openclaw/agent-cowork/*.md

# archive 內被卡住的（status ≠ done）
grep -L '^status: done' ~/.openclaw/agent-cowork/archive/2026-08/*.md
```

---

## 檔案清單

| 檔案 | 用途 |
|------|------|
| `SKILL.md` | 完整協議（給 agent 讀） |
| `README.md` | 本檔（給主人看） |
| `.template.md` | 訊息骨架（給 agent 複製） |
| `HEARTBEAT-snippet.md` | heartbeat SOP 片段（給各 agent 貼） |
| `archive/` | 過期訊息（處理完就搬來這） |
| `*-to-*-*.md` | 訊息檔案（主目錄 = 未讀） |

---

*維護者：大寶 · v1.1 2026-08-17 13:53*
