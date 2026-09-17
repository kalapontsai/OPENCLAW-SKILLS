---
name: "livestream-recorder"
description: "Record multi-hour live streams via yt-dlp + ffmpeg. Auto-retry, URL discovery, OpenClaw cron monitoring. Tested 28h+ streams."
status: proposal
version: "v1"
date: "2026-09-17T04:19:35.364Z"
---

# Livestream Recorder

Records multi-hour live streams (HLS, Periscope, YouTube Live) using yt-dlp + BtbN ffmpeg with auto-retry, automatic stream URL discovery, and OpenClaw cron monitoring. Designed for unattended operation across multi-day broadcasts.

## When to use

Use when recording a live stream for later viewing:

- Conference talks, livestream events, multi-day broadcasts
- Stream duration 30 minutes to 28+ hours
- Sources: Periscope, Twitter/X Live, YouTube Live, Luma events, Mux HLS
- Cloudflare-gated sources (via cookie refresh)
- Multi-day events with off-hours gaps between daily sessions

Do not use for: short recordings under 30 minutes, DRM-protected streams, on-demand video (use direct yt-dlp).

## Core principle

- **yt-dlp** extracts live stream m3u8 URL from page or uses direct URL
- **ffmpeg (BtbN build)** demuxes HLS into MPEG-TS segments (invoked internally by yt-dlp)
- **record-loop.sh** wraps yt-dlp with auto-retry every 5 seconds on stream drop
- **OpenClaw automations** drive the timeline: warmup, auto-grab, start, heartbeat, stop
- **Periscope rotation** handled automatically: playback IDs change daily, retry loop re-extracts them

## One-time setup

Install tools in WSL/Linux:

```
# yt-dlp (latest)
curl -L https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp -o ~/.local/bin/yt-dlp
chmod +x ~/.local/bin/yt-dlp

# ffmpeg (BtbN build required - johnvansickle segfaults on HLS)
curl -L https://github.com/BtbN/FFmpeg-Builds/releases/latest/download/ffmpeg-master-latest-linux64-gpl.tar.xz | tar xJ
mv ffmpeg-master-latest-linux64-gpl/bin/{ffmpeg,ffprobe} ~/.local/bin/
```

Create working directory structure:

```
mkdir -p /path/to/record-loop/{bin,run,recordings,recordings-process,logs,config}
```

Write `run/stream.env`:

```
STREAM_URL=""           # empty = wait for auto-grab; or paste direct m3u8 URL
SEGMENT_SECONDS=3600    # split .ts every 1 hour
MAX_DISK_PCT=85         # delete oldest if disk exceeds this
GDRIVE_REMOTE=""        # optional: rclone remote for cloud backup
```

## Stream URL auto-discovery

`bin/auto-grab.sh` tries paths in order, succeeds on first m3u8 found:

1. Direct stream URL (already in stream.env)
2. Luma join URL: `https://luma.com/join/{guest_key}`
3. Luma with cookies: same URL + `--add-header "Cookie: $(cat run/luma_cookie_header.txt)"`
4. Platform-specific (x.ai/galaxy, etc.) with their cookies
5. Public Mux/Periscope URL patterns

On failure: write flag to `/tmp/auto-grab-failed.flag`. Cron at T-2min reads flag and sends user fallback message via webchat. User opens page in browser, F12 to Network, filters `.m3u8`, pastes URL in chat. Agent writes URL to `stream.env`, `watch-url.sh` triggers `start.sh` automatically.

Cookie refresh cadence for Cloudflare: cf_clearance cookies expire in 30-60 minutes. Refresh within 30 minutes of stream start (not hours before). Export method: Chrome DevTools to Network, any request, Request Headers, Cookie: line, Copy value.

## Recording daemon

`bin/start.sh` launches `bin/record-loop.sh` as fully detached daemon:

- `setsid + nohup` detaches from terminal
- Writes PID to `run/recorder.pid`
- Logs to `logs/recorder.out.log` (stdout) and `logs/record.log` (yt-dlp output)
- Each iteration creates new .ts file with timestamp `_a${ATTEMPT}.ts`
- Files under 1MB treated as failed and auto-deleted
- Disk cleanup: removes 3 oldest .ts if disk exceeds MAX_DISK_PCT

`bin/stop.sh` sends SIGTERM to PID, daemon catches signal and exits cleanly.

`bin/status.sh` reports PID alive status with uptime, disk usage, all .ts files with size and timestamp, and last 5 record.log lines.

## OpenClaw automation timeline

Schedule at start of stream (T = stream start, all times in event timezone):

| Time | Name | Type | Target | Delivery | Purpose |
|------|------|------|--------|----------|---------|
| T-35min | warmup | agentTurn | current | announce | verify system ready |
| T-5min | auto-grab | script | main | none | discover stream URL |
| T-2min | notify-fail | agentTurn | current | announce | alert user if grab failed |
| T | smart-start | script | main | none | launch start.sh if URL set |
| T+5min | verify | agentTurn | current | announce | confirm recording started |
| T+6h | heartbeat | script | main | none | silent unless FAIL |
| T+12h | heartbeat | script | main | none | silent unless FAIL |
| T+18h | heartbeat | script | main | none | silent unless FAIL |
| T+~33h | stop+report | agentTurn | current | announce | final summary |

Schedule format example:

```
schedule: {kind:"at", at:"2026-09-15T23:25:00+08:00"}
sessionTarget: main | current
payload: {kind:"script", script:"bash /path/to/bin/cron-X.sh"}
        or
payload: {kind:"agentTurn", message:"warmup checklist..."}
delivery: {mode:"announce"} for user-visible; {mode:"none"} for silent watchers
```

Helper wrappers in `bin/cron-*.sh` simplify cron payload and avoid shell escaping issues in OpenClaw job config.

## Heartbeat monitoring

`bin/heartbeat.sh` checks PID alive, newest .ts file over 1MB and modified under 10min ago, record.log last entry under 10min ago, and disk usage.

Status levels: OK means all green and logs silently. WARN means file stale but PID alive, expected during off-hours for daily streams. FAIL means PID dead or no .ts file, alerts user via Telegram or webchat.

Run via OpenClaw cron with `delivery.mode:"none"`, only escalate on FAIL.

## Recovery patterns

**Periscope daily rotation**: yt-dlp returns 404 on stale URL, loop retries, re-extracts URL, new .ts file auto-created. No user action needed.

**Cloudflare blocks yt-dlp**: HTTP 403 indicates cookies expired, user refreshes via Chrome DevTools, pastes new cookie header.

**Stream offline between sessions**: yt-dlp retries fail with 404, heartbeat shows WARN but PID alive. Recording loop persists, resumes when stream restarts.

**Disk full**: `record-loop.sh` cleanup_old_files() removes 3 oldest .ts if disk over 85%.

**WSL crash**: Use Windows Task Scheduler with `wsl.exe -e bash -c "bash /path/to/start.sh"` for auto-recovery on boot.

## Post-processing (after stream ends)

Merge all .ts segments to single file:

```
cd recordings/
for f in *.ts; do echo "file '$PWD/$f'"; done > /tmp/concat.txt
ffmpeg -f concat -safe 0 -i /tmp/concat.txt -c copy ../recordings-process/full.ts
```

H.265 compress with CRF 28: CPU (libx265) takes 8 GB to ~1.4 GB but slow (~30 fps encoding, many hours), GPU (hevc_nvenc for NVIDIA) is real-time at 1-2 hours for 8 GB. Audio uses `-c:a copy` to avoid re-encoding:

```
ffmpeg -i full.ts -c:v libx265 -crf 28 -preset medium -c:a copy compressed.mp4
```

Upload to cloud (optional): `rclone copy recordings-process/ gdrive:galaxy-recordings/`

## Verification

```
ls -lh recordings/*.ts              # all segments present
ffprobe recordings-process/full.ts  # duration, codecs, bitrate
du -sh recordings/                  # total size
```

Confirm duration matches broadcast schedule (for example 28h for 3-day event).

## Pitfalls

- **cf_clearance expires in 30-60 min** — refresh close to stream start, not hours before
- **Playback IDs rotate daily** — never reuse URLs across days on Periscope
- **johnvansickle ffmpeg segfaults on HLS** — always use BtbN build
- **WSL cron service not installed by default** — use OpenClaw automations instead of crontab
- **Cookie files need chmod 600** — they contain auth tokens
- **Auto-grab can fail** — keep fallback message path open so user can paste URL manually
- **`.ts` files split on time or size** — use SEGMENT_SECONDS=3600 for hourly chunks
- **Recording must be detached** — setsid + nohup + PID file required
- **Off-hours = expected WARN** — heartbeat shows WARN not FAIL during daily session gaps
- **temp.ts orphan files** — yt-dlp sometimes leaves .temp.ts alongside finished .ts; clean up after stream ends

## Reference

Tested with Grok Bot Galaxy livestream Sept 15-17, 2026 (xAI / Periscope CDN, Cloudflare-gated Luma registration, 28h continuous across 3 days with off-hours). Successfully captured Day 1 (4.5 GB), Day 2 (3.8 GB), with Day 3 in progress using same automated pipeline.

Support scripts in `scripts/`: record-loop.sh, start.sh, stop.sh, status.sh, auto-grab.sh, heartbeat.sh, smart-start.sh, watch-url.sh, cron-autograb.sh, cron-heartbeat.sh, cron-smartstart.sh, cron-stop.sh, notify-failure.sh, disk-watch.sh.
