#!/usr/bin/env python3
"""
warden.py — WSL 端 polling daemon。

輪詢：
  /mnt/d/.../agent-bulletin/data/.refresh-trigger
  /mnt/d/.../agent-bulletin/data/.writeback-*.json

動作：
  - .refresh-trigger 出現 → 跑 sync_bulletin.py,刪 trigger
  - .writeback-*.json 出現 → 跑 writeback.py,刪 payload

輪詢間隔 2 秒。背景 daemon（start_warden.sh 用 setsid nohup 啟）。
"""
import subprocess
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

TZ = timezone(timedelta(hours=8))
REPO_DIR = Path.home() / ".openclaw" / "workspace-two" / "repos" / "agents-bulletin"
DATA_DIR = Path("/mnt/d/docker-volumn/ubuntu-apache2/html/agent-bulletin/data")
REFRESH_TRIGGER = DATA_DIR / ".refresh-trigger"
LOG_FILE = Path.home() / ".openclaw" / "agent-cowork" / "warden.log"
PID_FILE = Path.home() / ".openclaw" / "agent-cowork" / "warden.pid"

POLL_INTERVAL_SEC = 2.0


def log(msg: str) -> None:
    line = f"[{datetime.now(TZ).strftime('%H:%M:%S')}] {msg}"
    print(line, flush=True)
    try:
        LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        with LOG_FILE.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def run_script(label: str, args: list[str]) -> int:
    log(f"{label} start: {' '.join(args)}")
    try:
        r = subprocess.run(args, capture_output=True, text=True, timeout=30)
        rc = r.returncode
        out = (r.stdout or "").strip()
        err = (r.stderr or "").strip()
        if out:
            log(f"{label} stdout: {out[:400]}")
        if err and rc != 0:
            log(f"{label} stderr: {err[:400]}")
        log(f"{label} end rc={rc}")
        return rc
    except Exception as e:
        log(f"{label} fail: {e}")
        return 99


def scan_once() -> None:
    # 1. refresh trigger
    if REFRESH_TRIGGER.exists():
        log("refresh trigger detected")
        try:
            REFRESH_TRIGGER.unlink()
        except Exception as e:
            log(f"remove trigger fail: {e}")
            return
        run_script(
            "sync",
            [sys.executable, str(REPO_DIR / "scripts" / "sync_bulletin.py")],
        )

    # 2. writeback payloads
    for wb in sorted(DATA_DIR.glob(".writeback-*.json")):
        log(f"writeback detect: {wb.name}")
        rc = run_script(
            "writeback",
            [sys.executable, str(REPO_DIR / "scripts" / "writeback.py"), str(wb)],
        )
        if rc == 0:
            try:
                wb.unlink()
                log(f"writeback removed: {wb.name}")
            except Exception as e:
                log(f"writeback remove fail: {e}")
        else:
            # 寫入失敗：把 payload 改名加 .failed，避免下次又被撿
            log(f"writeback rc={rc}, rename to .failed")
            try:
                wb.rename(wb.with_suffix(wb.suffix + ".failed"))
            except Exception as e:
                log(f"rename fail: {e}")


def main() -> int:
    # 寫 PID
    try:
        PID_FILE.write_text(str(__import__("os").getpid()), encoding="utf-8")
    except Exception:
        pass

    log(f"warden start (pid={__import__('os').getpid()}, data={DATA_DIR})")
    while True:
        try:
            scan_once()
        except Exception as e:
            log(f"scan err: {e}")
        time.sleep(POLL_INTERVAL_SEC)


if __name__ == "__main__":
    sys.exit(main())
