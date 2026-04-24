# 🤖 Hermes Video Agent — Content Bridge

> An autonomous AI video processing system powered by the **Hermes 3** language model. It handles end-to-end workflows: video extraction, multilingual translation, OCR text replacement, subtitle burning, creative script rewriting, and cross-platform publishing — all orchestrated by an AI agent with tool-calling capabilities.

---

## 📋 Table of Contents

- [Architecture Overview](#-architecture-overview)
- [What is Hermes?](#-what-is-hermes)
- [Prerequisites](#-prerequisites)
- [Installation](#-installation)
- [Configuration](#-configuration)
- [Running the App](#-running-the-app)
- [Usage Guide](#-usage-guide)
- [Tech Stack](#-tech-stack)
- [Troubleshooting](#-troubleshooting)

---

## 🏗️ Architecture Overview

The system has **two modes**, both powered by the **Hermes AI Orchestrator**:

### Mode 1: Full Pipeline (Video Translation & Publishing)
```
Video URL → Download (yt-dlp / Playwright)
          → Transcribe Audio (Whisper — local, no API needed)
          → Translate Subtitles (Kimi K2.6 AI)
          → Detect & Replace On-Screen Text via OCR (EasyOCR + FFmpeg)
          → Extract Keyframes & Generate AI Summary (Kimi Vision)
          → Burn Dual-Language Subtitles (FFmpeg)
          → Auto-Publish to X/Twitter (Playwright)
```

### Mode 2: Script Extractor (Creative Rewriting)
```
Video URL → Download → Transcribe → Extract Keyframes → AI Summary
          → Kimi K2.6 Cinematic Script Rewrite (5 scenes + image prompts)
```

**Supported Platforms:** YouTube, TikTok, Douyin (Chinese TikTok)
**Supported Languages:** Vietnamese, English, Chinese, Japanese, Korean

---

## 🧠 What is Hermes?

**Hermes 3** is an open-source large language model developed by [Nous Research](https://nousresearch.com/) that excels at **function calling** (tool use) and **agentic reasoning**. In this system, Hermes acts as the **brain** — the autonomous orchestrator that decides which tools to call, in what order, and how to handle errors.

### How Hermes Works in This System

```
┌──────────────────────────────────────────────────────┐
│                   HERMES AGENT                       │
│  (AI Orchestrator — decides what to do next)         │
│                                                      │
│  System Prompt: "You are the Hermes Content Bridge   │
│  Agent. You have access to these tools..."           │
│                                                      │
│  ┌────────────┐  ┌────────────┐  ┌────────────┐     │
│  │ download   │  │ transcribe │  │ translate  │     │
│  │ _video     │  │ _video     │  │ _content   │     │
│  └────────────┘  └────────────┘  └────────────┘     │
│  ┌────────────┐  ┌────────────┐  ┌────────────┐     │
│  │ render_    │  │ publish_   │  │ rewrite_   │     │
│  │ subtitles  │  │ to_x       │  │ script     │     │
│  └────────────┘  └────────────┘  └────────────┘     │
└──────────────────────────────────────────────────────┘
```

1. **System Prompt**: Hermes receives a detailed prompt defining its role and available tools (JSON function schemas)
2. **Planning**: Given a user's video URL and target language, Hermes creates a plan: `download → transcribe → translate → render → publish`
3. **Tool Execution**: At each step, Hermes generates a function call (e.g., `download_video(url="...")`), the system executes it, and returns the result
4. **Adaptive Loop**: If a tool fails, Hermes can retry, skip, or suggest an alternative — it's not a hardcoded pipeline

### Hermes Provider Options

You can run Hermes through different providers:

| Provider | Model | Description |
|----------|-------|-------------|
| **Kimi** (Recommended) | `kimi-k2.6` | Moonshot AI's model — fast, multilingual, affordable. Powers translation, vision, and orchestration |
| **OpenRouter** | `nousresearch/hermes-3-llama-3.1-405b` | The original Hermes 3 405B model via OpenRouter. Most capable but more expensive |
| **Self-hosted** | Any OpenAI-compatible | Run your own Hermes via vLLM, Ollama, or any OpenAI-compatible server |

### Key Agent Files

| File | Role |
|------|------|
| `backend/agent/hermes_agent.py` | Agent initialization, system prompt, and the agentic loop (plan → call tool → observe → repeat) |
| `backend/agent/tools.py` | Tool definitions (JSON schemas) and execution handlers |
| `backend/workers/pipeline.py` | Pipeline execution with real-time WebSocket progress updates |

---

## ✅ Prerequisites

Before installing, make sure you have the following on your system:

| Tool | Version | How to Install |
|------|---------|----------------|
| **Python** | 3.11+ | [python.org/downloads](https://www.python.org/downloads/) |
| **Node.js** | 20+ | [nodejs.org](https://nodejs.org/) |
| **FFmpeg** | Latest | Windows: [gyan.dev/ffmpeg](https://www.gyan.dev/ffmpeg/builds/) — add to PATH<br>Linux: `sudo apt install ffmpeg` |
| **Git** | Latest | [git-scm.com](https://git-scm.com/) |

### Verify Installation
```bash
python --version    # Should show 3.11+
node --version      # Should show v20+
ffmpeg -version     # Should show version info
git --version       # Should show version info
```

---

## 🚀 Installation

### Step 1: Clone the Repository
```bash
git clone https://github.com/ntclick/hermes-video-agent.git
cd hermes-video-agent
```

### Step 2: Set Up Python Backend
```bash
# Create virtual environment
python -m venv venv

# Activate it
# Windows:
venv\Scripts\activate
# Linux/Mac:
source venv/bin/activate

# Install Python dependencies
pip install -r requirements.txt

# Install Playwright browsers (needed for Douyin download & X publishing)
playwright install chromium
```

### Step 3: Set Up Next.js Frontend
```bash
cd frontend
npm install
cd ..
```

### Step 4: Install the Hermes Agent Framework

The Hermes agent is built into the codebase — no separate installation needed. It uses the **OpenAI Python SDK** (already in `requirements.txt`) to communicate with your chosen AI provider via the standard Chat Completions API with function calling.

If you want to run the original **Hermes 3 model locally** (optional, advanced):
```bash
# Option A: Via Ollama (easiest for local hosting)
curl -fsSL https://ollama.ai/install.sh | sh
ollama pull hermes3

# Then set in .env:
# HERMES_PROVIDER=custom
# HERMES_API_KEY=ollama
# HERMES_BASE_URL=http://localhost:11434/v1
# HERMES_MODEL=hermes3

# Option B: Via OpenRouter (cloud, no GPU needed)
# Get an API key at https://openrouter.ai
# Then set in .env:
# HERMES_PROVIDER=openrouter
# HERMES_API_KEY=your_openrouter_key
# HERMES_BASE_URL=https://openrouter.ai/api/v1
# HERMES_MODEL=nousresearch/hermes-3-llama-3.1-405b
```

> **Note:** By default, the system uses **Kimi K2.6** as both the orchestrator and the translation/vision engine. This is the recommended setup because Kimi handles all tasks (translation, OCR, vision summary, script rewriting) in a single provider. You only need a Kimi API key to get started.

---

## 🔑 Configuration

### Step 1: Create your `.env` file
```bash
cp .env.example .env
```

### Step 2: Get API Keys

You need **at least one** AI provider API key to run the pipeline:

| Variable | Required? | Description | Where to Get |
|----------|-----------|-------------|--------------|
| `KIMI_API_KEY` | ✅ **Required** | Kimi K2.6 — powers translation, OCR text replacement, tweet generation, and multimodal vision | [platform.moonshot.cn](https://platform.moonshot.cn) (Free tier available) |
| `HERMES_API_KEY` | Optional | Hermes 3 agent orchestration via OpenRouter (only if you want to use Hermes 3 instead of Kimi) | [openrouter.ai](https://openrouter.ai) |
| `FAL_API_KEY` | Optional | AI cover image generation via Flux | [fal.ai](https://fal.ai) |

### Step 3: Edit your `.env` file

Open `.env` in any text editor and fill in your keys:

```env
# --- REQUIRED: Kimi AI (Translation + Vision + OCR + Orchestration) ---
KIMI_API_KEY=your_kimi_api_key_here
KIMI_BASE_URL=https://api.moonshot.cn/v1

# --- Hermes Agent Provider ---
# "kimi" = Use Kimi for everything (recommended, simplest setup)
# "openrouter" = Use Hermes 3 via OpenRouter for orchestration
# "custom" = Use your own self-hosted model
HERMES_PROVIDER=kimi
HERMES_MODEL=kimi-k2.6

# --- App Settings ---
APP_HOST=0.0.0.0
APP_PORT=8000
LOG_LEVEL=INFO

# --- Whisper (local speech-to-text, runs entirely on your machine, no API key needed) ---
# Options: tiny, base, small, medium, large-v3
# "base" is recommended for speed vs accuracy balance
WHISPER_MODEL=base
```

### Optional: X/Twitter Auto-Publishing

To enable automatic posting to X, configure X account cookies through the web dashboard (Settings page) after starting the app. No manual `.env` editing needed.

### Optional: Douyin (Chinese TikTok) Support

Douyin requires browser cookies to bypass anti-bot protection. Paste Netscape-format cookies in the Settings page of the dashboard.

---

## ▶️ Running the App

### Quick Start (Windows)
```powershell
python start_windows.py
```
This launches both the backend API (port 8000) and frontend dashboard (port 3000) simultaneously.

### Manual Start (Any OS)
```bash
# Terminal 1: Start Backend API
python -m uvicorn backend.main:app --host 0.0.0.0 --port 8000 --reload

# Terminal 2: Start Frontend Dashboard
cd frontend
npm run dev
```

### Open the Dashboard
Navigate to **[http://localhost:3000](http://localhost:3000)** in your browser.

---

## 📖 Usage Guide

### Full Pipeline (Translate & Publish Videos)

1. Open the dashboard at `http://localhost:3000`
2. Click **🎬 Full Pipeline** in the top navigation
3. Paste a YouTube / TikTok / Douyin video URL
4. Select your **target language** (e.g., English, Vietnamese)
5. Optionally toggle **Auto-post** and select an X account
6. Click **Start Hermes** → The AI agent will:
   - Download the video
   - Transcribe spoken audio with Whisper (locally, no API)
   - Translate subtitles to your chosen language
   - Detect and blur/replace hardcoded on-screen text (EasyOCR)
   - Extract keyframes and generate an AI summary
   - Burn dual-language subtitles into the video
   - Optionally auto-publish to X/Twitter
7. Watch the **Live Logs** tab to see the agent's real-time decision-making
8. Download the final video or view it directly in the dashboard

### Script Extractor (Creative Mode)

1. Click **📝 Script Extractor** in the top navigation
2. Paste a video URL and select language
3. Click **Extract Script** → Hermes will:
   - Download and transcribe the video
   - Extract keyframes and create an AI visual summary
   - Rewrite the content into 5 cinematic scenes with narration and AI image prompts
4. View the original video, AI summary, keyframes, and rewritten script in the Overview tab

---

## 📦 Tech Stack

| Layer | Technology |
|-------|-----------|
| **AI Agent** | Hermes 3 (Nous Research) / Kimi K2.6 (Moonshot AI) — function calling orchestration |
| **Backend** | Python 3.12, FastAPI, SQLAlchemy (async), SQLite |
| **Frontend** | Next.js 15, React 19, TypeScript |
| **Speech-to-Text** | Whisper (OpenAI, runs locally — no API key needed) |
| **OCR** | EasyOCR (runs locally — no API key needed) |
| **Video Processing** | FFmpeg (subtitle burning, OCR box-blur, re-encoding) |
| **Download** | yt-dlp, Playwright (Douyin anti-bot bypass) |
| **Publishing** | Playwright (automated X/Twitter posting) |
| **Process Manager** | PM2 (production), Caddy (reverse proxy + SSL) |

---

## 🐛 Troubleshooting

### "FFmpeg not found"
Make sure FFmpeg is installed and added to your system PATH:
```bash
ffmpeg -version
```
Windows: Download from [gyan.dev/ffmpeg](https://www.gyan.dev/ffmpeg/builds/) and add the `bin` folder to your PATH environment variable.

### "Whisper model download slow"
The first run downloads the Whisper model (~140MB for `base`). This is cached after the first download. If it's slow, try using `tiny` model in your `.env`:
```
WHISPER_MODEL=tiny
```

### "EasyOCR is very slow"
EasyOCR uses PyTorch and runs on CPU by default. On a machine without GPU, OCR processing can take 3-5 minutes per video. The system will still produce subtitled videos even if OCR is slow — it's non-blocking.

### "Douyin download fails"
Douyin aggressively blocks automated access. Solutions:
1. Add fresh browser cookies via the Settings page in the dashboard
2. Try a different Douyin URL format (use `/video/ID` instead of modal links)

### "X/Twitter publishing fails"
1. Make sure you've added X account cookies via Settings
2. Cookies expire — re-add them if publishing suddenly stops working
3. Check the Live Logs tab for detailed error messages

### "Kimi API errors"
1. Verify your API key is correct in `.env`
2. Check your Kimi account balance at [platform.moonshot.cn](https://platform.moonshot.cn)
3. The system auto-retries failed API calls, check logs for details

### Windows: "NotImplementedError" on asyncio
This is automatically handled by the app. If you still see it, make sure you're using Python 3.11+.

---

## 🔒 Security Notes

- All API keys are stored server-side in `.env` and never exposed to the frontend
- The dashboard is designed for local/internal use
- For public deployment, add authentication (e.g., Caddy Basic Auth, Cloudflare Access)
- X account cookies are stored encrypted in the local SQLite database

---

## 📄 License

MIT
