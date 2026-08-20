#!/usr/bin/env python3
"""
writeback.py — 處理一個 writeback payload (data/.writeback-<thread_id>.json)。

寫回 ~/.openclaw/agent-cowork/<thread>.md：
  - 在「💬 對話紀錄」(或「❓ 待決策 Q&A」若有且 action=answer) append 新 section
  - 更新 frontmatter: last_actor=master, last_action_at=now
  - 若 action=answer 且 frontmatter flags.awaiting-decision 含 master → 移除

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
MASTER = "master"  # writeback 的來源:view.html / index.html 的 QA 都是 master(大大)送出的。
                     # thread frontmatter 的 to: 陣列才是誰該讀這條訊息的 source of truth,
                     # 不該再在 section header 上重複標作者。

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
    """在主目錄找 thread 檔。

    匹配優先序:
      1. frontmatter `thread_id:` 欄位(對應 bulletin manifest 的 thread_id)
      2. md_path.stem(對應 sync_bulletin.py line 61 的 fallback)

    archive 不納入(即使 match 也不回傳 — 不可寫)。

    為什麼不用 glob:bulletin 的 thread_id 是 frontmatter 內的獨立欄位,
    不一定對應到檔名片段。範例:`thread_id: 2026-08-19-workspace-tidy`
    vs 檔名 `one-thread-2026-08-19_2231_workspace-tidy-for-two.md` —
    glob 完全 match 不到(rc=4 慘案,2026-08-20)。
    """
    for md_path in sorted(SRC_DIR.glob("*.md")):
        if "archive" in md_path.parts:
            continue
        # 1. frontmatter thread_id match
        try:
            raw = md_path.read_text(encoding="utf-8")
            m = FRONTMATTER_RE.match(raw)
            if m:
                try:
                    meta = yaml.safe_load(m.group(1)) or {}
                except yaml.YAMLError:
                    meta = None
                if meta and meta.get("thread_id") == thread_id:
                    return md_path
        except Exception:
            pass
        # 2. stem match(對應 sync_bulletin.py 的 fallback)
        if md_path.stem == thread_id:
            return md_path
    return None


def list_available_thread_ids() -> str:
    """列出主目錄所有可用 thread_id,給 rc=4 失敗訊息用,協助 debug。"""
    items = []
    for md in sorted(SRC_DIR.glob("*.md")):
        if "archive" in md.parts:
            continue
        tid = None
        try:
            raw = md.read_text(encoding="utf-8")
            m = FRONTMATTER_RE.match(raw)
            if m:
                try:
                    meta = yaml.safe_load(m.group(1)) or {}
                    tid = meta.get("thread_id")
                except yaml.YAMLError:
                    pass
        except Exception:
            pass
        items.append(f"{tid or md.stem} ({md.name})")
    if len(items) > 10:
        return ", ".join(items[:10]) + f", ... ({len(items)} total)"
    return ", ".join(items) if items else "(none)"


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
        print(f"   available thread_ids: {list_available_thread_ids()}", file=sys.stderr)
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
    # 注意:不標作者名(thread frontmatter to: 陣列已決定誰要讀,再標是多餘 + 會誤導)
    if action == "answer":
        head = f"### A · {stamp}"
        if decision:
            head += f" · decision: {decision}"
    elif action == "instruction":
        head = f"### 📝 指示 · {stamp}"
    elif action == "request_close":
        head = f"### 🔚 請結案 · {stamp}"
    else:
        head = f"### reply · {stamp}"

    new_section = f"\n{head}\n{text}\n"

    # 決定插入位置
    if action == "answer" and QA_MARKER in body:
        body = append_into_section(body, QA_MARKER, new_section)
    elif CHAT_MARKER in body:
        body = append_into_section(body, CHAT_MARKER, new_section)
    else:
        body = body + new_section + "\n"

    # 更新 frontmatter
    meta["last_actor"] = MASTER
    meta["last_action_at"] = now_iso

    flags = meta.get("flags")
    if action == "answer" and isinstance(flags, dict):
        awaiting = flags.get("awaiting-decision")
        if isinstance(awaiting, list):
            if MASTER in awaiting:
                awaiting.remove(MASTER)
                if not awaiting:
                    flags.pop("awaiting-decision", None)
        elif awaiting == MASTER:
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
