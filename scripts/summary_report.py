#!/usr/bin/env python3
"""
agent-cowork v1.7.0 §6.6 — 維護者全域 thread 摘要匯報
對應 SKILL.md §6.6 / HEARTBEAT-snippet.md「維護者專屬 SOP」

Usage:
  python3 summary_report.py               # 一般跑（依節流決定要不要送）
  python3 summary_report.py --force       # 強制送（跳過節流）
  python3 summary_report.py --dry-run     # 只 print，不送、不寫 cache
  python3 summary_report.py --json        # 只 print JSON，不送、不寫 cache
  python3 summary_report.py --init-cache  # 建立 baseline cache，不送

設計：
  - 觀察者視角：不 append / 不 archive / 不動 thread
  - 只給「維護者」（§11.0 per host 1 個，本機 = agent-one）跑
  - 節流：hash 比對 .summary-cache.json → 變動才送 / 6hr 狀態心跳
  - 訊息用 message 工具送到 USER.md 主人 telegram（chat_id = 8774080801）
"""
import os, re, json, hashlib, sys, argparse, subprocess
from datetime import datetime, timezone, timedelta

# ───────────────────── 設定 ─────────────────────
TZ = timezone(timedelta(hours=8))
COWORK_DIR = os.path.expanduser('~/.openclaw/agent-cowork')
CACHE = os.path.join(COWORK_DIR, '.summary-cache.json')
MY_NAME = 'one'  # 維護者（agent-one / 大寶）。若別 host 維護者不同，改這行
OWNER_CHAT_ID = 'telegram:8774080801'  # 主人 USER.md = 8774080801
EXCLUDE_FILES = ('SKILL.md', 'README.md', 'CHANGELOG.md',
                 '.template.md', 'HEARTBEAT-snippet.md', '.summary-cache.json')


def now_iso():
    return datetime.now(TZ).isoformat()


def parse_frontmatter(path):
    with open(path, 'r', encoding='utf-8') as f:
        content = f.read()
    if not content.startswith('---'):
        return None
    parts = content.split('---', 2)
    if len(parts) < 3:
        return None
    fm = {}
    for line in parts[1].strip().split('\n'):
        m = re.match(r'^(\w[\w_.-]*):\s*(.*)', line)
        if not m:
            continue
        key, val = m.group(1), m.group(2).strip()
        if val.startswith('[') and val.endswith(']'):
            fm[key] = [x.strip().strip('"\'') for x in val[1:-1].split(',') if x.strip()]
        else:
            fm[key] = val.strip('"\'')
    return fm


def scan_threads():
    threads = []
    for f in sorted(os.listdir(COWORK_DIR)):
        if not f.endswith('.md'):
            continue
        if f in EXCLUDE_FILES:
            continue
        if f.endswith('.bak') or 'proposal' in f:
            continue
        if f.startswith('.'):
            continue
        path = os.path.join(COWORK_DIR, f)
        fm = parse_frontmatter(path)
        if not fm:
            continue
        threads.append({
            'file': f,
            'thread_id': fm.get('thread_id', ''),
            'initiator': fm.get('initiator', ''),
            'to': fm.get('to', ''),
            'status': fm.get('status', ''),
            'priority': fm.get('priority', 'normal'),
            'last_actor': fm.get('last_actor', ''),
            'last_action_at': fm.get('last_action_at', ''),
            'subject': fm.get('subject', ''),
            'flags': fm.get('flags', ''),
        })
    return threads


def hash_state(threads):
    payload = []
    for t in threads:
        am = ''
        m = re.search(r'awaiting-master-decision:\s*(\w+)', t.get('flags', ''))
        if m:
            am = m.group(1)
        payload.append(f"{t['thread_id']}|{t['status']}|{t['priority']}|{t['last_action_at']}|{am}")
    return hashlib.md5('|'.join(sorted(payload)).encode()).hexdigest()


def load_cache():
    if not os.path.exists(CACHE):
        return None
    try:
        return json.load(open(CACHE))
    except Exception:
        return None


def save_cache(stats, current_hash):
    with open(CACHE, 'w', encoding='utf-8') as f:
        json.dump({
            'hash': current_hash,
            'sent_at': now_iso(),
            'stats': stats,
        }, f, ensure_ascii=False, indent=2)


def age_str(iso, now):
    try:
        t = datetime.fromisoformat(iso.replace('Z', '+00:00'))
        if t.tzinfo is None:
            t = t.replace(tzinfo=TZ)
        diff = (now - t).total_seconds()
        if diff < 0:
            return 'new'
        if diff < 86400:
            return f"{int(diff/3600)}h"
        return f"{int(diff/86400)}d"
    except Exception:
        return '?'


def in_for_me(t):
    to = t['to']
    if to == 'all':
        return True
    if isinstance(to, list):
        return MY_NAME in to
    return to == MY_NAME


def awaiting_master(t):
    m = re.search(r'awaiting-master-decision:\s*master', t.get('flags', ''))
    return bool(m) and t['status'] not in ('done', 'cancelled')


def is_critical(t):
    return t['status'] == 'open' and t['priority'] == 'critical'


def my_acceptance(t):
    return t['initiator'] == MY_NAME and t['status'] == 'awaiting-acceptance'


def is_stale(t, now):
    try:
        t_time = datetime.fromisoformat(t['last_action_at'].replace('Z', '+00:00'))
        if t_time.tzinfo is None:
            t_time = t_time.replace(tzinfo=TZ)
        return (now - t_time).total_seconds() > 72*3600 \
            and t['status'] not in ('done', 'cancelled')
    except Exception:
        return False


def compute_stats(threads, now):
    return {
        'total': len(threads),
        'for_me': sum(1 for t in threads if in_for_me(t)),
        'awaiting_master': sum(1 for t in threads if awaiting_master(t)),
        'critical': sum(1 for t in threads if is_critical(t)),
        'awaiting_my_acceptance': sum(1 for t in threads if my_acceptance(t)),
        'stale': sum(1 for t in threads if is_stale(t, now)),
        'other': sum(
            1 for t in threads
            if t['status'] not in ('done', 'cancelled')
            and not in_for_me(t)
            and not awaiting_master(t)
            and not is_critical(t)
            and not my_acceptance(t)
            and not is_stale(t, now)
        ),
    }


def section(title, items, fmt, limit=8):
    if not items:
        return []
    out = [title, '']
    for t in items[:limit]:
        out.append('• ' + fmt(t))
    if len(items) > limit:
        out.append(f"（...還有 {len(items)-limit} 個未列）")
    out.append('')
    return out


def render_message(threads, stats, now):
    lines = [
        f"📋 Cowork 全域摘要 ({now.strftime('%H:%M')})",
        '',
        f"▸ 總數 {stats['total']} | 給我 {stats['for_me']} | "
        f"等主人 {stats['awaiting_master']} | critical {stats['critical']}",
        '',
    ]
    lines += section(f"🔴 critical ({stats['critical']}):",
                     [t for t in threads if is_critical(t)],
                     lambda t: f"{t['subject']} · {t['initiator']}→{t['to']} · "
                               f"{age_str(t['last_action_at'], now)}")
    lines += section(f"🟡 等主人 ({stats['awaiting_master']}):",
                     [t for t in threads if awaiting_master(t)],
                     lambda t: f"{t['subject']} · {t['initiator']}→{t['to']} · "
                               f"{age_str(t['last_action_at'], now)}")
    lines += section(f"🟢 給我 ({stats['for_me']}):",
                     [t for t in threads if in_for_me(t)],
                     lambda t: f"{t['subject']} · {t['initiator']}→{t['to']} · "
                               f"{t['status']} · {age_str(t['last_action_at'], now)}")
    lines += section(f"📦 等我驗收 ({stats['awaiting_my_acceptance']}):",
                     [t for t in threads if my_acceptance(t)],
                     lambda t: f"{t['subject']} · last:{t['last_actor']} · "
                               f"{age_str(t['last_action_at'], now)}")
    lines += section(f"⏰ 停滯 > 3 天 ({stats['stale']}):",
                     [t for t in threads if is_stale(t, now)],
                     lambda t: f"{t['subject']} · last:{t['last_actor']} · "
                               f"{age_str(t['last_action_at'], now)}")
    lines += section(f"🟦 主目錄其他活躍 ({stats['other']}):",
                     [
                         t for t in threads
                         if t['status'] not in ('done', 'cancelled')
                         and not in_for_me(t)
                         and not awaiting_master(t)
                         and not is_critical(t)
                         and not my_acceptance(t)
                         and not is_stale(t, now)
                     ],
                     lambda t: f"{t['subject']} · {t['initiator']}→{t['to']} · "
                               f"{t['status']} · {age_str(t['last_action_at'], now)}")
    return '<pre>\n' + '\n'.join(lines) + '\n</pre>'


def send_to_telegram(message):
    """用 openclaw 自己的 message 工具送到主人 telegram。
    Fallback：若 subprocess 失敗，留 stderr 給 caller 處理。
    """
    cmd = [
        'openclaw', 'message', 'send',
        '--target', OWNER_CHAT_ID,
        '--message', message,
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        return result.returncode == 0, result.stdout + result.stderr
    except Exception as e:
        return False, str(e)


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--force', action='store_true',
                   help='跳過節流強制送')
    p.add_argument('--dry-run', action='store_true',
                   help='只 print，不送、不寫 cache')
    p.add_argument('--json', action='store_true',
                   help='只 print JSON stats，不送、不寫 cache')
    p.add_argument('--init-cache', action='store_true',
                   help='只建立 baseline cache，不送')
    args = p.parse_args()

    now = datetime.now(TZ)
    threads = scan_threads()
    current_hash = hash_state(threads)
    stats = compute_stats(threads, now)
    cache = load_cache()

    last_hash = cache.get('hash') if cache else None
    last_sent = cache.get('sent_at') if cache else None
    hours_since = 999
    if last_sent:
        try:
            last_t = datetime.fromisoformat(last_sent)
            hours_since = (now - last_t).total_seconds() / 3600
        except Exception:
            pass

    if args.init_cache:
        save_cache(stats, current_hash)
        print(f'✅ baseline cache written to {CACHE}')
        print(f'   hash={current_hash[:16]} stats={stats}')
        return 0

    should_send = args.force or (current_hash != last_hash) \
                  or (hours_since >= 6) or (cache is None)

    if args.json:
        print(json.dumps({
            'stats': stats,
            'hash': current_hash,
            'last_hash': last_hash,
            'hours_since': hours_since,
            'should_send': should_send,
            'force': args.force,
        }, ensure_ascii=False, indent=2))
        return 0

    message = render_message(threads, stats, now)

    if args.dry_run:
        print(f'[dry-run] should_send={should_send}')
        print(f'[dry-run] stats={stats}')
        print(f'[dry-run] hash={current_hash[:16]} '
              f'(last={last_hash[:16] if last_hash else "None"}, '
              f'since {hours_since:.1f}h)')
        print(message)
        return 0

    if not should_send:
        print(f'⏭ 跳過（節流）：hash 一致且距上次 {hours_since:.1f}h < 6h')
        print(f'  stats={stats}')
        return 0

    ok, out = send_to_telegram(message)
    if ok:
        save_cache(stats, current_hash)
        print(f'✅ sent to {OWNER_CHAT_ID} ({len(message)} chars)')
        print(f'  hash={current_hash[:16]} stats={stats}')
    else:
        print(f'❌ send failed: {out}', file=sys.stderr)
        print(f'  message 預存到 /tmp/cowork-summary-msg.txt')
        with open('/tmp/cowork-summary-msg.txt', 'w') as f:
            f.write(message)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
