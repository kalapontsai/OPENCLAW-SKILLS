# livestream-recorder

Multi-hour live stream recorder with auto-retry, URL discovery, and OpenClaw cron monitoring.

## TL;DR

Record long live streams (HLS, Periscope, YouTube Live, Luma events) to local `.ts` files using `yt-dlp + BtbN ffmpeg`. Built for unattended operation across multi-day broadcasts.

Tested with Grok Bot Galaxy livestream (Sept 15-17, 2026, xAI / Periscope CDN, 28h continuous across 3 days).

## Features

- **Auto-retry on stream drop**: yt-dlp wrapper retries every 5 seconds when stream goes offline
- **Automatic stream URL discovery**: 4-path fallback (direct → Luma join → cookies → Mux pattern)
- **OpenClaw cron timeline**: warmup → auto-grab → start → heartbeat → stop all scheduled
- **Cookie-aware**: handles Cloudflare-gated sources via Chrome DevTools cookie export
- **Periscope rotation handling**: playback IDs change daily, retry loop re-extracts them automatically
- **Heartbeat monitoring**: silent OK/WARN, alerts only on FAIL
- **Disk management**: auto-cleans oldest segments when disk fills up
- **Post-processing helpers**: merge segments + H.265 CRF 28 compression

## Install

Clone this repo into your workspace skills directory:

```
cd ~/.openclaw/workspace/skills/
git clone https://github.com/kalapontsai/OPENCLAW-SKILLS.git /tmp/openclaw-skills-tmp
cp -r /tmp/openclaw-skills-tmp/livestream-recorder ./livestream-recorder
```

Or just download the `livestream-recorder/` folder.

## What's in here

```
livestream-recorder/
├── SKILL.md                  # Full procedure + recovery patterns + pitfalls
└── scripts/
    ├── record-loop.sh        # Main recording loop with auto-retry
    ├── start.sh / stop.sh / status.sh
    ├── auto-grab.sh          # Multi-path stream URL discovery
    ├── heartbeat.sh          # Health check
    ├── smart-start.sh        # Conditional start with fallback notification
    ├── watch-url.sh          # Polls stream.env for manual URL paste
    ├── cron-*.sh             # OpenClaw automation wrappers
    ├── notify-failure.sh     # Fallback alert script
    └── disk-watch.sh         # Disk cleanup + optional rclone
```

## Quick Start

See `SKILL.md` for the full procedure. TL;DR:

```
# 1. Install tools
curl -L https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp -o ~/.local/bin/yt-dlp
chmod +x ~/.local/bin/yt-dlp
# (See SKILL.md for BtbN ffmpeg install — johnvansickle segfaults on HLS)

# 2. Set up directory
mkdir -p /path/to/record-loop/{bin,run,recordings,recordings-process,logs,config}
cp scripts/* /path/to/record-loop/bin/

# 3. Configure stream URL (or leave empty for auto-discovery)
echo 'STREAM_URL=""' > /path/to/record-loop/run/stream.env

# 4. Start recording
bash /path/to/record-loop/bin/start.sh
```

## Tested

- **Grok Bot Galaxy Livestream** (Sept 15-17, 2026): 28h continuous across 3 days, xAI / Periscope CDN, Cloudflare-gated Luma registration, automatic Periscope playback ID rotation handled by retry loop. Captured Day 1 (4.5 GB) and Day 2 (3.8 GB) successfully with no manual intervention.

## License

MIT (same as parent repo)
