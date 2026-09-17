<!--
訊息模板 ─ 複製本檔，改 frontmatter 跟 body。
v1.7.0：thread 集中單檔，responder 只 append 不另開新檔
v1.7.0 新增：維護者（per host 1 個）會另跑 §6.6 全域摘要匯報，跟本檔獨立
檔名：<initiator>-thread-YYYY-MM-DD_HHMM_<topic>-for-<receiver>.md
存到 ~/.openclaw/agent-cowork/（主目錄 = 活躍 thread 看板）
closeout 由 initiator archive 整檔
-->

---
thread_id: <id>                                  # = 檔名去 .md
initiator: <sender>                              # 必填：stock / two / one / three
to: <receiver>                                   # 必填：單一 / 陣列 / all
participants: [<receiver>]                       # 預期會 append 的人
status: open                                     # open / awaiting-acceptance / done / cancelled / blocked
priority: normal                                 # critical / high / normal / low
created: 2026-08-18T13:00:00+08:00               # 必填：ISO-8601 + 時區
last_actor: <sender>                             # 必填：最後動作的人
last_action_at: 2026-08-18T13:00:00+08:00        # 必填：最後動作時間
subject: 一行總結（≤60字）                       # 必填
---

# Thread 標題（人話版）

## 📌 摘要（給 responder 先看，3 行內）
1. 重點 1
2. 重點 2
3. 重點 3

## 詳細內容
（背景、脈絡、資料、修法建議、驗收標準）

---

## 💬 對話紀錄（append-only）

### <sender> · 2026-08-18 13:00 · 開 thread / 派工
（從「詳細內容」段搬過來的完整 body）

---

*<sender> · <時間> Asia/Taipei · 發起 thread 至 agent-cowork · v1.7.0*
