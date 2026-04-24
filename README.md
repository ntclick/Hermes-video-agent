# 🤖 Hermes Content Bridge

An autonomous AI video pipeline that downloads, transcribes, translates, and publishes short-form videos to X/Twitter — orchestrated by the **Hermes Agent** via function-calling.

**Supported sources:** YouTube · TikTok · Douyin  
**Supported languages:** Vietnamese · English · Chinese · Japanese · Korean

---

## Table of Contents

- [How It Works](#how-it-works)
- [What Is the Hermes Agent?](#what-is-the-hermes-agent)
- [Prerequisites](#prerequisites)
- [Installation](#installation)
- [Configuration](#configuration)
- [Running the App](#running-the-app)
- [Using the Dashboard](#using-the-dashboard)
- [BYOK (Bring Your Own Key)](#byok-bring-your-own-key)
- [Tech Stack](#tech-stack)
- [Deploy to VPS](#deploy-to-vps)
- [Troubleshooting](#troubleshooting)

---

## How It Works

### Full Pipeline

```
Video URL
  ↓ yt-dlp / Playwright (Douyin)
  ↓ Whisper (local speech-to-text)
  ↓ Kimi K2.6 (translation)
  ↓ EasyOCR + FFmpeg (on-screen text replacement)
  ↓ FFmpeg (keyframe extraction)
  ↓ Kimi Vision (AI summary)
  ↓ FFmpeg (subtitle burn)
  ↓ Playwright (publish to X/Twitter)
```

The entire flow runs in the background. The dashboard streams live logs and progress via WebSocket.

### Script Extractor Mode

Downloads and transcribes a video, then uses Kimi K2.6 to rewrite the content as a 5-scene cinematic script with image prompts — useful for repurposing content without publishing.

### AI Cover Video (Optional)

After a job completes, generate a short AI-illustrated cover video using FLUX (fal.ai) images composed with the original audio, Ken Burns effects, and translated subtitles.

---

## What Is the Hermes Agent?

**Hermes** is an AI orchestrator that uses function-calling (tool use) to drive the pipeline. Instead of a hardcoded sequence of steps, Hermes is given a system prompt defining its role and a set of tools, then autonomously decides what to call and in what order.

```
User submits URL
    │
    ▼
Hermes Agent (Kimi K2.6 or Hermes 3 via OpenRouter)
    │
    ├─ calls download_video(url)
    ├─ calls transcribe_video(job_id)
    ├─ calls translate_content(job_id, target_language)
    ├─ calls render_with_subtitles(job_id)
    └─ calls publish_to_x(job_id)        ← only if auto-publish enabled
```

Each tool call result is returned to the agent. If a step fails, Hermes can observe the error and adapt (retry, skip, report).

### Agent Provider Options

| Provider | When to Use |
|----------|-------------|
| **Kimi K2.6** (default) | Simplest setup. One API key powers translation, vision, summary, tweet generation, and orchestration |
| **OpenRouter — Hermes 3 405B** | Use the original Hermes 3 model for orchestration. Requires an OpenRouter key |
| **Custom / Self-hosted** | Any OpenAI-compatible endpoint (Ollama, vLLM, LM Studio) |

Switch providers in the **Settings** page of the dashboard without editing any files.

---

## Prerequisites

| Tool | Version | Notes |
|------|---------|-------|
| Python | 3.11+ | |
| Node.js | 20+ | |
| FFmpeg | Any recent | Must be on PATH |
| Git | Any | |

```bash
python --version   # 3.11+
node --version     # v20+
ffmpeg -version    # any version line
```

---

## Installation

### 1. Clone

```bash
git clone https://github.com/ntclick/hermes-video-agent.git
cd hermes-video-agent
```

### 2. Python backend

```bash
# Create and activate virtual environment
python -m venv venv

# Windows
venv\Scripts\activate
# Linux / Mac
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Install Playwright browser (needed for Douyin download + X publishing)
playwright install chromium
```

### 3. Frontend

```bash
cd frontend
npm install
cd ..
```

### 4. Environment file

```bash
cp .env.example .env
```

Open `.env` and fill in at minimum:

```env
KIMI_API_KEY=your_kimi_key_here
```

See [Configuration](#configuration) for all options.

---

## Configuration

### Minimal `.env` (Kimi only)

```env
# Kimi K2.6 — powers translation, vision, summary, and agent orchestration
KIMI_API_KEY=your_key_here
KIMI_BASE_URL=https://api.moonshot.cn/v1

# Hermes agent uses Kimi by default
HERMES_PROVIDER=kimi
HERMES_MODEL=kimi-k2.6

# Whisper model size: tiny / base / small / medium / large-v3
# "base" recommended — good accuracy, ~140MB download on first run
WHISPER_MODEL=base
```

Get a Kimi API key at [platform.moonshot.cn](https://platform.moonshot.cn). Free tier is available.

### Using Hermes 3 via OpenRouter (optional)

```env
HERMES_PROVIDER=openrouter
HERMES_API_KEY=your_openrouter_key
HERMES_BASE_URL=https://openrouter.ai/api/v1
HERMES_MODEL=nousresearch/hermes-3-llama-3.1-405b

# Still need Kimi for translation and vision
KIMI_API_KEY=your_kimi_key
```

### Self-hosted model (Ollama, vLLM, etc.)

```env
HERMES_PROVIDER=custom
HERMES_API_KEY=any_value
HERMES_BASE_URL=http://localhost:11434/v1
HERMES_MODEL=hermes3
```

### Optional keys

| Variable | Purpose |
|----------|---------|
| `FAL_API_KEY` | AI cover video image generation (FLUX via fal.ai) |

X account cookies and Douyin cookies are configured in the **Settings page** of the dashboard — no `.env` editing needed.

---

## Running the App

### Windows (one command)

```powershell
python start_windows.py
```

### Any OS (two terminals)

```bash
# Terminal 1 — backend API (port 8000)
python -m uvicorn backend.main:app --host 0.0.0.0 --port 8000 --reload

# Terminal 2 — frontend dashboard (port 3000)
cd frontend
npm run dev
```

Open **http://localhost:3000** in your browser.

---

## Using the Dashboard

### Starting a Job

1. Paste a YouTube, TikTok, or Douyin URL
2. Choose a target language
3. Toggle **Auto-post** and select an X account if you want automatic publishing
4. Click **Start Hermes**

### Overview Tab

Shows the full status of the selected job:

- **Pipeline progress** bar with stage labels
- **Hermes Agent** card — current tool being called and which service handles it
- **Keyframes** — extracted video frames (click to enlarge)
- **AI Summary** — multimodal summary generated from keyframes + transcript
- **Post to X** section:
  - If already posted: shows tweet link
  - If not posted: editable caption, account selector, and **Post to X** button

### Video Tab

Plays the rendered output video (with burned subtitles) and the AI cover video if generated.

### Logs Tab

Real-time streaming logs from the Hermes agent — every tool call, API response, and pipeline decision.

### Manual Publish

If you ran a job without auto-publish, or want to post to a different account:

1. Open a completed job → Overview tab
2. Edit the caption if needed
3. Select an X account from the dropdown
4. Click **🚀 Post to X**

Hermes will generate a tweet caption from the AI summary (if none exists) and publish via Playwright.

### AI Cover Video

Available on completed jobs that have an AI summary:

- **Generate AI Cover** — rewrites content into 5 scenes, generates FLUX images, composes video with original audio
- **Re-compose Cover** — reuses existing scenes, re-renders the video
- **Rewrite Cover** — new Kimi script + new FLUX images

---

## BYOK (Bring Your Own Key)

You can provide API keys per-session via the **Settings page** in the dashboard instead of `.env`. Keys are stored in browser `localStorage` only — never sent to or stored on the server (except transiently during a running job, then cleared).

This allows multiple users with different API keys to share one deployment.

Keys that can be provided via BYOK:

| Key | Purpose |
|-----|---------|
| Kimi API Key | Translation, vision, summary |
| Hermes API Key | Agent orchestration (if using OpenRouter) |
| FAL API Key | AI cover image generation |
| Douyin Cookies | Douyin video download |
| X Cookies | X/Twitter publishing |

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| AI Agent | Kimi K2.6 / Hermes 3 (function-calling) |
| Backend | Python 3.11+, FastAPI, SQLAlchemy async, SQLite |
| Frontend | Next.js 15, React 19, TypeScript |
| Speech-to-Text | OpenAI Whisper (runs locally, no API key) |
| OCR | EasyOCR (runs locally, no API key) |
| Video | FFmpeg — subtitle burn, keyframe extraction, re-encoding |
| Download | yt-dlp (YouTube/TikTok), Playwright (Douyin) |
| AI Images | fal.ai FLUX (AI cover generation) |
| Publishing | Playwright (headless Chromium → X/Twitter) |
| Real-time | WebSocket (live log streaming) |
| Process Manager | PM2 (production) |

---

## Deploy to VPS

### Requirements

| | Minimum | Recommended |
|---|---|---|
| CPU | 2 cores | 4+ cores |
| RAM | 4 GB | 8 GB |
| Disk | 20 GB | 50 GB |
| OS | Ubuntu 20.04+ | Ubuntu 22.04 |

### Setup

```bash
# System packages
apt update && apt upgrade -y
apt install -y python3.12 python3.12-venv python3-pip ffmpeg git curl

# Node.js 20
curl -fsSL https://deb.nodesource.com/setup_20.x | bash -
apt install -y nodejs

# PM2
npm install -g pm2

# Playwright deps
npx playwright install-deps chromium

# Project
cd /opt
git clone https://github.com/ntclick/hermes-video-agent.git content-bridge
cd content-bridge

python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
playwright install chromium

cd frontend && npm install && npm run build && cd ..

cp .env.example .env
nano .env   # add your KIMI_API_KEY
```

### Start with PM2

```bash
pm2 start ecosystem.config.js
pm2 save
pm2 startup   # follow printed command to enable auto-start
```

### Update

```bash
cd /opt/content-bridge
git pull origin main
source venv/bin/activate
pip install -r requirements.txt
cd frontend && npm run build && cd ..
pm2 restart all
```

### HTTPS with Caddy (optional)

```
your-domain.com {
  reverse_proxy /api/* 127.0.0.1:8000
  reverse_proxy /ws/*  127.0.0.1:8000
  reverse_proxy        127.0.0.1:3000
}
```

---

## Troubleshooting

**FFmpeg not found**  
Add FFmpeg to your PATH. On Windows download from [gyan.dev/ffmpeg](https://www.gyan.dev/ffmpeg/builds/).

**Whisper slow on first run**  
It downloads the model (~140 MB for `base`) once. Use `WHISPER_MODEL=tiny` for faster but less accurate transcription.

**Douyin download fails**  
Add fresh browser cookies via Settings. Use the `/video/ID` URL format, not modal links.

**X/Twitter publish fails**  
Cookies expire. Re-paste them in Settings → X Accounts. Check the Logs tab for the specific error.

**EasyOCR slow**  
Runs on CPU — 2–5 minutes per video is normal. OCR is non-blocking; the pipeline continues even if it's slow.

**`Could not copy Chrome cookie database`**  
Your system `yt-dlp` config has `--cookies-from-browser chrome`. The app runs `yt-dlp --no-config` to avoid this, so restarting the backend after pulling the latest code should fix it.

---

## License

MIT
