# 🤖 Hermes Video Agent — Content Bridge

> **Hermes Agent Creative Hackathon** — Nous Research
>
> An autonomous AI agent powered by **Hermes** that handles end-to-end video processing: extraction, multilingual translation, OCR text replacement, subtitle burning, and cross-platform publishing.

---

## 📋 Table of Contents

- [How It Works](#-how-it-works)
- [Prerequisites](#-prerequisites)
- [Installation](#-installation)
- [Configuration](#-configuration)
- [Running the App](#-running-the-app)
- [Usage Guide](#-usage-guide)
- [Tech Stack](#-tech-stack)
- [Troubleshooting](#-troubleshooting)

---

## 🎬 How It Works

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
Video URL → Download → Transcribe → Kimi K2.6 Cinematic Script Rewrite
```
Breaks down any video into creative scenes with AI image prompts and localized narration.

**Supported Platforms:** YouTube, TikTok, Douyin (Chinese TikTok)
**Supported Languages:** Vietnamese, English, Chinese, Japanese, Korean

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
| `KIMI_API_KEY` | ✅ **Required** | Kimi K2.6 — powers translation, OCR text replacement, tweet writing, and multimodal vision | [platform.moonshot.cn](https://platform.moonshot.cn) (Free tier available) |
| `HERMES_API_KEY` | Optional | Hermes 3 agent orchestration via OpenRouter | [openrouter.ai](https://openrouter.ai) |
| `FAL_API_KEY` | Optional | AI cover image generation via Flux | [fal.ai](https://fal.ai) |

### Step 3: Edit your `.env` file

Open `.env` in any text editor and fill in your keys:

```env
# --- REQUIRED: Kimi AI (Translation + Vision + OCR) ---
KIMI_API_KEY=your_kimi_api_key_here
KIMI_BASE_URL=https://api.moonshot.cn/v1

# --- Hermes Agent Provider ---
# Options: "kimi" (recommended, uses Kimi for everything)
#          "openrouter" (uses Hermes 3 via OpenRouter for orchestration)
HERMES_PROVIDER=kimi
HERMES_MODEL=kimi-k2.6

# --- App Settings ---
APP_HOST=0.0.0.0
APP_PORT=8000
LOG_LEVEL=INFO

# --- Whisper (local speech-to-text, no API key needed) ---
# Options: tiny, base, small, medium, large-v3
# "base" is recommended for speed vs accuracy balance
WHISPER_MODEL=base
```

### Optional: X/Twitter Auto-Publishing

To enable automatic posting to X, you'll configure cookies through the web dashboard (Settings page) after starting the app. No manual `.env` editing needed for X.

### Optional: Douyin (Chinese TikTok) Support

Douyin requires browser cookies to bypass anti-bot protection. You can paste Netscape-format cookies in the Settings page of the dashboard.

---

## ▶️ Running the App

### Quick Start (Windows)
```powershell
python start_windows.py
```
This launches both the backend (port 8000) and frontend (port 3000).

### Manual Start
```bash
# Terminal 1: Start Backend
python -m uvicorn backend.main:app --host 0.0.0.0 --port 8000 --reload

# Terminal 2: Start Frontend
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
   - Transcribe spoken audio (Whisper)
   - Translate subtitles to your chosen language (Kimi K2.6)
   - Detect and replace hardcoded on-screen text (EasyOCR)
   - Extract keyframes and generate an AI summary
   - Burn dual-language subtitles into the video
   - Optionally publish to X/Twitter
7. Download the final video or view it directly in the dashboard

### Script Extractor (Creative Mode)

1. Click **📝 Script Extractor** in the top navigation
2. Paste a video URL and select language
3. Click **Extract Script** → Hermes will:
   - Download and transcribe the video
   - Rewrite the content into 5 cinematic scenes
   - Generate AI image prompts for each scene
4. View the original video, AI summary, keyframes, and rewritten script

---

## 🧠 Hermes Agent Integration

The core AI orchestration uses the **Hermes 3 Model** via function calling:

1. **System Prompt**: The agent acts as an autonomous video processing orchestrator
2. **Tool Definitions**: JSON schemas define available tools (`download_video`, `transcribe_video`, `translate_content`, `render_with_subtitles`, etc.)
3. **Execution Loop**: Hermes evaluates context, calls tools sequentially, and decides the next step based on results

**Key Files:**
- `backend/agent/hermes_agent.py` — Agent initialization and orchestration loop
- `backend/agent/tools.py` — Tool definitions and execution handlers
- `backend/workers/pipeline.py` — Pipeline execution with real-time WebSocket updates

---

## 📦 Tech Stack

| Layer | Technology |
|-------|-----------|
| **Backend** | Python 3.12, FastAPI, SQLAlchemy (async), SQLite |
| **Frontend** | Next.js 15, React 19, TypeScript |
| **AI Models** | Kimi K2.6 (Moonshot AI), Whisper (OpenAI, local), EasyOCR (local) |
| **Video** | FFmpeg (subtitle burning, OCR box-blur, re-encoding) |
| **Download** | yt-dlp, Playwright (Douyin anti-bot bypass) |
| **Publishing** | Playwright (automated X/Twitter posting) |
| **Deploy** | PM2, Caddy (reverse proxy + SSL) |

---

## 🐛 Troubleshooting

### "FFmpeg not found"
Make sure FFmpeg is installed and added to your system PATH:
```bash
ffmpeg -version
```
If it doesn't work, download from [gyan.dev/ffmpeg](https://www.gyan.dev/ffmpeg/builds/) and add the `bin` folder to your PATH.

### "Whisper model download slow"
The first run downloads the Whisper model (~140MB for `base`). This is cached after the first download. If it's slow, try using `tiny` model in your `.env`:
```
WHISPER_MODEL=tiny
```

### "EasyOCR is very slow"
EasyOCR uses PyTorch and runs on CPU by default. On a machine without GPU, OCR processing can take 3-5 minutes per video. To skip OCR, the system will still produce subtitled videos without on-screen text replacement.

### "Douyin download fails"
Douyin aggressively blocks automated access. Solutions:
1. Add fresh browser cookies via the Settings page in the dashboard
2. Try a different Douyin URL format (use `/video/ID` instead of modal links)

### "X/Twitter publishing fails"
1. Make sure you've added X account cookies via Settings
2. Cookies expire — re-add them if publishing suddenly stops working
3. Check the Live Logs tab for detailed error messages

### Windows-specific: "NotImplementedError" on asyncio
This is automatically handled by the app. If you still see it, make sure you're using Python 3.11+.

---

## 🔒 Security Notes

- All API keys are stored server-side in `.env` and never exposed to the frontend
- The dashboard is designed for local/internal use
- For public deployment, put the app behind authentication (e.g., Caddy Basic Auth, NextAuth.js)

---

## 📄 License

Built for the **Hermes Agent Creative Hackathon** by [Nous Research](https://nousresearch.com/).
