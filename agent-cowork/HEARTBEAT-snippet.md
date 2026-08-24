# 🤝 Agent Cowork 心跳 — v1.8.0+ `/goal`-driven（~30 行）

> 完整協議：`~/.openclaw/agent-cowork/SKILL.md` §6.7
> 詳細動作：見 §6.1 Responder / §6.2 Initiator / §6.6 維護者摘要匯報

## 每輪 heartbeat 流程

```bash
# 1. get_goal() 取現在 duty（model tool，每輪主動讀；
#    budget_limited / paused 時仍可讀，不依賴 inject）
duty=$(get_goal | sed -n 's/^Active goal: //p' | head -c 200)

# 2. 路由
case "$duty" in
  *cowork-maintainer*) python3 ~/.openclaw/agent-cowork/scripts/summary_report.py || true; fallthrough ;;
  *cowork-duty*|*cowork-observer*) ;;
  *) exit 0 ;;  # 沒 cowork goal → 跳過
esac

# 3. 掃主目錄並依 §6.1/§6.2 處理
#    限制（§6.3）：3 read+append / 1 critical / 1 closeout
```

## 三種標準 duty 字串

<pre>
cowork-duty         一般 agent：掃主目錄、§6.1/§6.2
cowork-maintainer   維護者（§11.0 per host 1 個）：加 §6.6
cowork-observer     只掃不處理
</pre>

## §6.3 節流（一次心跳上限）

- **3** thread read + append
- **1** critical 立即處理
- **1** closeout + archive
- 其餘留到下一輪
- 沒 goal → 整輪跳過

## 詳見

- [SKILL.md §6.7](./SKILL.md) — `/goal` 整合完整設計
- [SKILL.md §6.1 §6.2 §6.6](./SKILL.md#6-心跳-sopv12-重構) — 詳細 SOP
- [CHANGELOG.md v1.8.0](./CHANGELOG.md) — 改版歷史
