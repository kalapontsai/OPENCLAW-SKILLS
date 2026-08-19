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
        "flags": flags,
        "flag_awaiting_decision": flags.get("awaiting-decision") if isinstance(flags, dict) else None,
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

    for t in threads:
        grouped[t["category"]].append(t)
        flag = t.get("flag_awaiting_decision")
        if flag is not None:
            f_norm = flag if isinstance(flag, list) else [flag]
            if "two" in f_norm:
                pending_for_me.append(t["thread_id"])

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
        "groups": grouped,
    }

    MANIFEST_PATH.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    c = manifest["counts"]
    print(
        f"✅ synced {c['total']} threads → {MANIFEST_PATH}\n"
        f"   in_progress={c['in_progress']} paused={c['paused']} "
        f"closed={c['closed']} pending_for_two={len(pending_for_me)}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
