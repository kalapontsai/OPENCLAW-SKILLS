#!/usr/bin/env python3
"""
sync_bulletin.py — scan agent-cowork/*.md, write D:\\...\\agent-bulletin\\data\\.

讀取來源：~/.openclaw/agent-cowork/*.md（含 archive/）
輸出：
  data/manifest.json               ← 全部 thread 索引 + 狀態分組
  data/raw/<thread_id>.md          ← 原文（複製）
  data/raw/_archive/<...>.md       ← archive 原文
  data/threads/<thread_id>.json    ← 解析後結構化
"""
import json
import re
import shutil
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

import yaml

TZ = timezone(timedelta(hours=8))

# 來源與目標
SRC_DIR = Path.home() / ".openclaw" / "agent-cowork"
ARCHIVE_DIR = SRC_DIR / "archive"
DATA_DIR = Path("/mnt/d/docker-volumn/ubuntu-apache2/html/agent-bulletin/data")
RAW_DIR = DATA_DIR / "raw"
ARCH_RAW_DIR = RAW_DIR / "_archive"
THREADS_JSON_DIR = DATA_DIR / "threads"
MANIFEST_PATH = DATA_DIR / "manifest.json"
PREV_MANIFEST_PATH = DATA_DIR / "manifest.json.prev"  # v1.8.0: 比對變動用
TRIGGER_DIR = SRC_DIR  # ~/.openclaw/agent-cowork/.trigger-<agent>
CONSUMER_AGENTS = ("one", "two", "three", "stock")  # to=all 時的 broadcast 清單

# 排除
EXCLUDE_BASENAMES = {
    "SKILL.md", "README.md", ".template.md", "HEARTBEAT-snippet.md",
    "SKILL.md.bak-v1.1", ".template.md.bak-v1.1", "SKILL-v1.2-proposal.md",
}

# 狀態 → 分類
IN_PROGRESS_STATUSES = {"open", "awaiting-acceptance"}
PAUSED_STATUSES = {"blocked"}
CLOSED_STATUSES = {"done", "cancelled"}

FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)


def _stringify_dates(obj):
    """遞迴把 datetime 轉 isoformat 字串。YAML 拿到 ISO datetime 會轉成 datetime 物件，JSON 沒法序列化。"""
    if isinstance(obj, datetime):
        return obj.isoformat()
    if isinstance(obj, dict):
        return {k: _stringify_dates(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_stringify_dates(v) for v in obj]
    return obj


def parse_thread(md_path: Path) -> dict | None:
    """解析單一 thread .md，回傳 dict 或 None。"""
    try:
        text = md_path.read_text(encoding="utf-8")
    except Exception:
        return None
    m = FRONTMATTER_RE.match(text)
    if not m:
        return None
    try:
        meta = yaml.safe_load(m.group(1)) or {}
    except yaml.YAMLError:
        return None
    body = text[m.end():]

    thread_id = meta.get("thread_id") or md_path.stem
    flags = meta.get("flags") or {}

    return {
        "thread_id": thread_id,
        "filename": md_path.name,
        "rel_path": str(md_path.relative_to(SRC_DIR)),
        "initiator": meta.get("initiator", "?"),
        "to": meta.get("to"),
        "participants": meta.get("participants"),
        "status": meta.get("status", "open"),
        "priority": meta.get("priority", "normal"),
        "created": str(meta.get("created", "")),
        "last_actor": meta.get("last_actor", "?"),
        "last_action_at": str(meta.get("last_action_at", "")),
        "subject": meta.get("subject", "(無標題)"),
        "flags": _stringify_dates(flags) if isinstance(flags, dict) else flags,
        "flag_awaiting_decision": flags.get("awaiting-decision") if isinstance(flags, dict) else None,
        "flag_awaiting_master_decision": flags.get("awaiting-master-decision") if isinstance(flags, dict) else None,
        "closer": meta.get("closer"),
        "body_excerpt": extract_excerpt(body),
    }


def extract_excerpt(body: str, max_lines: int = 6) -> str:
    """從 ## 詳細內容 或開頭取幾行摘要。"""
    lines = body.split("\n")
    out = []
    in_detail = False
    for raw in lines:
        line = raw.rstrip()
        if line.startswith("# "):
            continue
        if line.startswith("## "):
            if in_detail and out:
                break
            if "詳細內容" in line or "詳情" in line or "摘要" in line:
                in_detail = True
                continue
            # 第一個 detail 之前不視為 detail
            if not in_detail:
                continue
            break
        if line.startswith("---"):
            continue
        if line.strip():
            out.append(line)
        if len(out) >= max_lines:
            break
    if not out:
        # fallback: 第一段
        for raw in lines:
            line = raw.strip()
            if line and not line.startswith("#") and not line.startswith("---"):
                out.append(line)
                if len(out) >= max_lines:
                    break
    return "\n".join(out[:max_lines]).strip()


def categorize(status: str, archived: bool = False) -> str:
    # 規則(簡潔版):
    # - closed 永遠 closed(不管檔案位置)
    # - 已在 archive/ 但非 closed(舊格式 / 未知 / 矛盾)→ 視為 paused
    # - main 的 open / awaiting-acceptance → in_progress
    # - 其他(perplexed) → paused
    if status in CLOSED_STATUSES:
        return "closed"
    if archived:
        return "paused"
    if status in IN_PROGRESS_STATUSES:
        return "in_progress"
    return "paused"  # 預設保險


def safe_copy(src: Path, dst: Path) -> bool:
    try:
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        return True
    except Exception as e:
        print(f"⚠️  copy fail {src} → {dst}: {e}", file=sys.stderr)
        return False


def compute_triggers(threads: list[dict]) -> dict[str, list[str]]:
    """v1.8.0: 比對前次 manifest，找出新增/變動的 thread，回傳 {agent: [tid...]}。

    規則：
      - 排除已 closed / 已 archived 的 thread（不觸發）
      - 「新增」或 last_action_at/status/priority 變動才觸發
      - to 欄位解析：
          * None / 'all' → 全部 consumer agents
          * list → 每個元素是 agent name
          * str → 單一 agent
    """
    prev: dict[str, dict] = {}
    if PREV_MANIFEST_PATH.exists():
        try:
            prev_data = json.loads(PREV_MANIFEST_PATH.read_text(encoding="utf-8"))
            for cat in ("in_progress", "paused", "closed"):
                for t in prev_data.get("groups", {}).get(cat, []):
                    prev[t["thread_id"]] = t
        except Exception:
            prev = {}

    triggers: dict[str, list[str]] = {}
    for t in threads:
        if t.get("archived") or t["status"] in CLOSED_STATUSES:
            continue
        tid = t["thread_id"]
        is_new = tid not in prev
        is_changed = False
        if not is_new:
            prev_t = prev[tid]
            if (prev_t.get("last_action_at") != t.get("last_action_at")
                    or prev_t.get("status") != t.get("status")
                    or prev_t.get("priority") != t.get("priority")):
                is_changed = True
        if not (is_new or is_changed):
            continue
        # 解析 to 欄位
        to = t.get("to")
        if to is None or to == "all":
            agents = list(CONSUMER_AGENTS)
        elif isinstance(to, list):
            agents = to
        else:
            agents = [to]
        for agent in agents:
            triggers.setdefault(agent, []).append(tid)
    return triggers


def write_triggers(triggers: dict[str, list[str]]) -> list[str]:
    """v1.8.0: 把 trigger 寫進 ~/.openclaw/agent-cowork/.trigger-<agent>。

    設計：merge 進現有 trigger 檔（避免被覆蓋丟失未消費的 thread_ids）。
    消費完由 check_warden.sh 刪除整個檔案。
    """
    written: list[str] = []
    for agent, tids in triggers.items():
        trigger_path = TRIGGER_DIR / f".trigger-{agent}"
        existing: dict = {"thread_ids": []}
        if trigger_path.exists():
            try:
                existing = json.loads(trigger_path.read_text(encoding="utf-8"))
            except Exception:
                existing = {}
        merged_ids = sorted(set(existing.get("thread_ids", []) + tids))
        payload = {
            "thread_ids": merged_ids,
            "written_at": datetime.now(TZ).isoformat(),
            "reason": "sync_bulletin detected new/changed threads",
            "source": "sync_bulletin.py",
        }
        trigger_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        written.append(f".trigger-{agent}({len(merged_ids)})")
    return written


def main() -> int:
    if not SRC_DIR.exists():
        print(f"❌ src dir not found: {SRC_DIR}", file=sys.stderr)
        return 1

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    THREADS_JSON_DIR.mkdir(parents=True, exist_ok=True)

    threads: list[dict] = []

    # 主目錄
    for md_path in sorted(SRC_DIR.glob("*.md")):
        if md_path.name in EXCLUDE_BASENAMES:
            continue
        if md_path.name.startswith("."):
            continue
        if ".bak" in md_path.name or "proposal" in md_path.name:
            continue
        info = parse_thread(md_path)
        if info is None:
            print(f"⚠️  skipped (parse fail): {md_path.name}", file=sys.stderr)
            continue
        info["archived"] = False
        info["category"] = categorize(info["status"], info["archived"])
        threads.append(info)
        safe_copy(md_path, RAW_DIR / f"{info['thread_id']}.md")
        try:
            (THREADS_JSON_DIR / f"{info['thread_id']}.json").write_text(
                json.dumps(info, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception as e:
            print(f"⚠️  write json fail {info['thread_id']}: {e}", file=sys.stderr)

    # archive（要保留 closed 資料，但不要同 thread_id 衝突）
    if ARCHIVE_DIR.exists():
        for md_path in sorted(ARCHIVE_DIR.rglob("*.md")):
            if md_path.name in EXCLUDE_BASENAMES:
                continue
            info = parse_thread(md_path)
            if info is None:
                continue
            info["archived"] = True
            info["category"] = categorize(info["status"], info["archived"])
            threads.append(info)
            try:
                rel = md_path.relative_to(ARCHIVE_DIR)
                arch_dst = ARCH_RAW_DIR / rel
                safe_copy(md_path, arch_dst)
            except Exception as e:
                print(f"⚠️  archive handle fail: {e}", file=sys.stderr)

    # 分組 + 待回覆清單
    grouped: dict[str, list[dict]] = {"in_progress": [], "paused": [], "closed": []}
    pending_for_me: list[str] = []
    pending_for_master: list[str] = []  # v1.6.1: agent escalate 的 thread 等主人決策

    for t in threads:
        grouped[t["category"]].append(t)
        flag = t.get("flag_awaiting_decision")
        if flag is not None:
            f_norm = flag if isinstance(flag, list) else [flag]
            if "two" in f_norm:
                pending_for_me.append(t["thread_id"])
        # v1.6.1: 過濾 awaiting-master-decision flag 且未 close
        if t.get("flag_awaiting_master_decision") == "master" and t["status"] not in ("done", "cancelled"):
            pending_for_master.append(t["thread_id"])

    # 排序（created desc）
    for k in grouped:
        grouped[k].sort(key=lambda x: x.get("created") or "", reverse=True)

    manifest = {
        "version": 1,
        "generated_at": datetime.now(TZ).isoformat(),
        "counts": {
            "in_progress": len(grouped["in_progress"]),
            "paused": len(grouped["paused"]),
            "closed": len(grouped["closed"]),
            "total": len(threads),
        },
        "pending_for_me": pending_for_me,
        "pending_for_master": pending_for_master,
        "groups": grouped,
    }

    MANIFEST_PATH.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    # v1.8.0: 計算 + 寫 trigger（給 check_warden.sh wake consumer agent）
    triggers = compute_triggers(threads)
    trigger_log = ""
    if triggers:
        written = write_triggers(triggers)
        trigger_log = " | triggers: " + " ".join(written)
    else:
        trigger_log = ""

    # 寫 prev manifest（給下次 sync 比對變動用）
    PREV_MANIFEST_PATH.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    c = manifest["counts"]
    print(
        f"✅ synced {c['total']} threads → {MANIFEST_PATH}\n"
        f"   in_progress={c['in_progress']} paused={c['paused']} "
        f"closed={c['closed']} pending_for_two={len(pending_for_me)} "
        f"pending_for_master={len(pending_for_master)}{trigger_log}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
