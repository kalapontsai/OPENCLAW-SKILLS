#!/usr/bin/env python3
"""
writeback.py — 處理一個 writeback payload (data/.writeback-<thread_id>.json)。

寫回 ~/.openclaw/agent-cowork/<thread>.md：
  - 在「💬 對話紀錄」(或「❓ 待決策 Q&A」若有且 action=answer) append 新 section
  - 更新 frontmatter: last_actor=two, last_action_at=now
  - 若 action=answer 且 frontmatter flags.awaiting-decision 含 two → 移除

⚠️ Refuse 寫入 archived thread。
"""
import json
import re
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

import yaml

TZ = timezone(timedelta(hours=8))
SRC_DIR = Path.home() / ".openclaw" / "agent-cowork"
DECIDER = "two"

FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)
QA_MARKER = "## ❓ 待決策 Q&A"
CHAT_MARKER = "## 💬 對話紀錄"


def append_into_section(body: str, marker: str, addition: str) -> str:
    """把 addition 插在 marker section 的尾端（下一個 ## header 之前）。"""
    idx = body.find(marker)
    if idx < 0:
        return body + "\n" + addition
    after = body[idx + len(marker):]
    next_section = re.search(r"\n##\s", after)
    if next_section:
        insert_at = idx + len(marker) + next_section.start()
        return body[:insert_at] + addition + body[insert_at:]
    return body + addition


def find_thread_file(thread_id: str) -> Path | None:
    """在主目錄找 thread 檔。archive 不允許寫。"""
    candidates = sorted(SRC_DIR.glob(f"*-{thread_id}.md"))
    if candidates:
        return candidates[0]
    candidates = sorted(SRC_DIR.glob(f"*{thread_id}*.md"))
    if candidates:
        return candidates[0]
    return None


def process(payload_path: Path) -> int:
    try:
        payload = json.loads(payload_path.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"❌ payload json parse fail: {e}", file=sys.stderr)
        return 2

    thread_id = payload.get("thread_id")
    action = payload.get("action", "answer")
    text = (payload.get("text") or "").strip()
    decision = payload.get("decision")

    if not thread_id or not text:
        print("❌ missing thread_id or text", file=sys.stderr)
        return 3

    target = find_thread_file(thread_id)
    if target is None:
        print(f"❌ thread not found in main dir: {thread_id}", file=sys.stderr)
        return 4
    # 防呆：archive 不可寫
    if "archive" in target.parts:
        print(f"❌ thread archived, refuse to write: {target}", file=sys.stderr)
        return 5

    raw = target.read_text(encoding="utf-8")
    m = FRONTMATTER_RE.match(raw)
    if not m:
        print(f"❌ no frontmatter: {target}", file=sys.stderr)
        return 6

    front_block = m.group(0)  # '---\n...\n---\n'
    body = raw[m.end():]
    try:
        meta = yaml.safe_load(m.group(1)) or {}
    except yaml.YAMLError as e:
        print(f"❌ yaml parse fail: {e}", file=sys.stderr)
        return 7

    now_iso = datetime.now(TZ).strftime("%Y-%m-%dT%H:%M:%S+08:00")
    stamp = datetime.now(TZ).strftime("%Y-%m-%d %H:%M")

    # 決定 section 標頭
    if action == "answer":
        head = f"### A · {stamp} · {DECIDER}"
        if decision:
            head += f" · decision: {decision}"
    elif action == "instruction":
        head = f"### 📝 指示 · {stamp} · {DECIDER}"
    elif action == "request_close":
        head = f"### 🔚 請結案 · {stamp} · {DECIDER}"
    else:
        head = f"### reply · {stamp} · {DECIDER}"

    new_section = f"\n{head}\n{text}\n"

    # 決定插入位置
    if action == "answer" and QA_MARKER in body:
        body = append_into_section(body, QA_MARKER, new_section)
    elif CHAT_MARKER in body:
        body = append_into_section(body, CHAT_MARKER, new_section)
    else:
        body = body + new_section + "\n"

    # 更新 frontmatter
    meta["last_actor"] = DECIDER
    meta["last_action_at"] = now_iso

    flags = meta.get("flags")
    if action == "answer" and isinstance(flags, dict):
        awaiting = flags.get("awaiting-decision")
        if isinstance(awaiting, list):
            if DECIDER in awaiting:
                awaiting.remove(DECIDER)
                if not awaiting:
                    flags.pop("awaiting-decision", None)
        elif awaiting == DECIDER:
            flags.pop("awaiting-decision", None)
        meta["flags"] = flags

    # 回寫（保留 YAML 順序，allow_unicode）
    new_front = "---\n" + yaml.safe_dump(
        meta, allow_unicode=True, sort_keys=False, default_flow_style=False
    ) + "---\n"
    target.write_text(new_front + body, encoding="utf-8")

    print(f"✅ wrote back to {target.name} (action={action})")
    return 0


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("usage: writeback.py <payload.json>", file=sys.stderr)
        sys.exit(1)
    sys.exit(process(Path(sys.argv[1])))
