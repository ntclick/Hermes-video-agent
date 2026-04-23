# 🌉 Hermes Video Agent (Content Bridge)

> **Hermes Agent Creative Hackathon** — Nous Research
>
> An autonomous AI agent powered by Hermes that handles end-to-end video processing: extraction, translation, transcription, visual dubbing (OCR), and cross-platform publishing.

## 🏗️ Architecture & Features

The system features two main operational modes driven by the **Hermes AI Orchestrator**:

### 🎬 1. Full Pipeline (Auto-Publishing)
```text
URL Input → Download (yt-dlp / Playwright) → Extract Audio & Transcribe (Whisper)
         → Translate Audio & Hardcoded Text (Kimi K2.6)
         → Computer Vision OCR & Boxblur (EasyOCR + FFmpeg)
         → Multimodal Scene Summary (Kimi Vision)
         → Generate Dual-Language Subtitles (SRT/ASS)
         → Burn Subtitles & Render (FFmpeg)
         → AI Cover Generation (Flux via Fal.ai)
         → Auto-Publish to X (Twitter API)
```

### 📝 2. Script Extractor (Creative Mode)
```text
URL Input → Download → Transcribe → Kimi K2.6 Rewrite (Cinematic Scene Breakdown)
```
- Automatically pulls Douyin/TikTok/YouTube videos.
- Transcribes and uses Kimi K2.6 to break down the video into creative scenes with AI Image Prompts and localized Narration in the target language (Vietnamese, English, Korean, Japanese, Chinese).

## 🚀 Key Technologies
- **🤖 Hermes Agent Orchestrator**: Uses function-calling to autonomously route tasks.
- **🧠 Kimi K2.6 (Moonshot AI)**: Context-aware translation, script rewriting, and multimodal vision analysis.
- **👁️ Computer Vision**: `EasyOCR` + OpenCV for tracking and blurring hardcoded Chinese text (e.g., cooking ingredients) and replacing it with translated text.
- **🎙️ Whisper (OpenAI)**: Local speech-to-text.
- **🎨 Flux (fal.ai)**: Generates highly engaging AI thumbnails.
- **🎬 FFmpeg**: Heavy-duty video processing, box-blurring, and subtitle burning.

## 🚀 Quick Start (VPS Deployment)

```bash
# 1. Clone to VPS
ssh root@your-vps
git clone https://github.com/ntclick/hermes-video-agent.git /opt/content-bridge
cd /opt/content-bridge

# 2. Run setup script (Installs Python venv, Node, PM2, FFmpeg, EasyOCR)
bash scripts/setup.sh

# 3. Add your API keys
cp .env.example .env
nano .env

# 4. Start the ecosystem with PM2
pm2 start ecosystem.config.js
```

## 🔑 Required Environment Variables (.env)

| Variable | Description | Where to get |
|----------|-------------|-------------|
| `KIMI_API_KEY` | Kimi K2.6 model access | [platform.moonshot.cn](https://platform.moonshot.cn) |
| `FAL_API_KEY` | Flux AI Image generation | [fal.ai](https://fal.ai) |
| `HERMES_API_KEY`| Hermes 3 Agent Orchestration | [openrouter.ai](https://openrouter.ai) |
| `TWITTER_API_KEY` | X Publishing | [developer.x.com](https://developer.x.com) |

## 🧠 Hermes Agent Integration Guide

The core of this project is driven by the **Hermes 3 Model** (via OpenRouter). The integration is built on **Function Calling (Tool Use)**:

1. **System Prompt**: The agent is initialized with a system prompt instructing it to act as an autonomous video orchestrator.
2. **Tool Definitions**: We provide JSON Schemas for various tools (e.g., `download_video`, `transcribe_video`, `rewrite_script`, `analyze_content`, `render_with_subtitles`).
3. **Execution Loop**: When a user submits a job, the backend triggers the agent. Hermes evaluates the context and responds with a `tool_call`. The backend executes the actual Python function (e.g., FFmpeg processing) and returns the result back to Hermes, which then decides the next step.

*Code Reference: See `backend/agent/hermes_agent.py` and `backend/agent/tools.py`.*

## 🔒 Security & Authentication

For the Hackathon presentation, the system is designed to run in a controlled VPS environment:
- **API Security**: The FastAPI backend can be secured using standard API Key validation (OAuth2/Bearer Tokens).
- **Frontend Protection**: The Next.js dashboard is meant for internal use. For public deployment, it is recommended to put the dashboard behind **Caddy Basic Auth** or integrate NextAuth.js.
- **Environment Variables**: All sensitive API keys (X/Twitter, Kimi, Hermes, Fal.ai) are strictly loaded via server-side `.env` and are never exposed to the client-side frontend.

## 📦 Tech Stack

- **Backend**: Python 3.12 + FastAPI + SQLAlchemy + PyTorch (EasyOCR)
- **Frontend**: Next.js 15 + React + TypeScript + Glassmorphic UI
- **Deploy**: PM2 + Caddy (Reverse Proxy) + SSL

## 📄 License
Built for the Hermes Agent Creative Hackathon by Nous Research.
