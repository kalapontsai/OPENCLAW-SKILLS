# agent-cowork 範例 thread（demo）

> 這目錄放真實跑完、closeout 過的完整 thread 當 demo。不是做作的範例 — 是 agent 在產線上實際跑出來的。

## 📂 目前 demo

| Demo | 說明 | 對應 SOP |
|------|------|----------|
| [`thread-2026-08-20_joke-telling-test.md`](./thread-2026-08-20_joke-telling-test.md) | 4 agent × 3 笑話 跨多輪心跳的協作測試，v1.6.1 `{...}` body 邊界 SOP 第一次實戰驗收 | `SKILL.md` §6.4 + §4.4.3 規則 6 |

## 🧭 為什麼這個 thread 適合當 demo

1. **多 agent 全到位** — one / two / three / stock 4 個都參與，每個連續 3 個心跳各講 3 個笑話
2. **跨多輪心跳** — 13:14 開 thread → 15:35 最後一個笑話 → 18:20 closeout
3. **v1.6.1 SOP 第一次實戰** — `{...}` body 邊界、decision 在 body 末尾都在這個 thread 第一次被驗證
4. **真實的 imperfect** — 故意保留失敗痕跡（超字 / typo / soft violation），不修飾，讓未來 reviewer 看到「真實能跑的 thread 長這樣」
5. **initiator closeout 完整示範** — 從 §6.2 流程到最後 archive 動作都在 closeout section 寫明

## 📚 Reading Guide

- 想看 v1.6.1 `{...}` body 格式：每個 `### <agent> · ... · 笑話 N` section 都示範
- 想看字數 SOP 怎麼踩雷：對照 closeout 段的 `字數驗收` 表 + source thread 的笑話 2 / 笑話 3
- 想看 initiator closeout 怎麼做：跳到 thread 結尾 `### one · 2026-08-20 18:20 · closeout ✅` section
- 想看「沒笑話也能 append」的進度觀察：`### one · 15:20 · 進度觀察（大寶不寫笑話 4）`

## 🔗 對應 source

Demo 是 **frozen snapshot** — 已經 closeout + archive。原始 source（含 live 修改軌跡）保留在：

```
~/.openclaw/agent-cowork/archive/2026-08/one-thread-2026-08-20_1314_joke-telling-test-for-all.md
```

## ⚠ 已知 SOP 漏洞（這個 demo 掀出來的）

1. **「50 字以內」沒統一計數法**（中英標點空格都算？英文單詞算？）
   - 建議下次 bump v1.6.2 / v1.7 明確化
2. **stock 標題 typo「話 3」非「笑話 3」** — 編號一致性可由 warden 自動驗
3. **開 thread / 派工 section body 用「（本體內容）」placeholder** — soft violation v1.6.1 §6.4（沒用 `{...}` 邊界）

---

*首次 demo 由 大寶 (agent-one) 2026-08-20 18:22 設立*
