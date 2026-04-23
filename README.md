# 🌉 Autonomous Content Bridge

> **Hermes Agent Creative Hackathon** — Nous Research
>
> Tự động tải video từ YouTube/TikTok/Douyin → Dịch phụ đề sang tiếng Việt → Đăng lên X (Twitter)

## 🏗️ Architecture

```
URL Input → Download (yt-dlp) → Transcribe (Whisper) → Translate (Kimi K2.5)
         → Generate Subtitles → Burn into Video (FFmpeg) → Publish to X
```

**Powered by:**
- 🤖 **Hermes Agent** — Autonomous orchestration via function calling
- 🧠 **Kimi K2.5** (Moonshot AI) — Translation & content analysis
- 🎙️ **Whisper** (OpenAI) — Speech-to-text transcription
- 🎬 **FFmpeg** — Video processing & subtitle rendering
- 🐦 **Twitter API v2** — Auto-publishing

## 🚀 Quick Start

```bash
# 1. Clone to VPS
ssh root@your-vps
cd /opt/content-bridge

# 2. Run setup
bash scripts/setup.sh

# 3. Add your API keys
nano .env

# 4. Start with PM2
pm2 start ecosystem.config.js
```

## 🔑 Required API Keys

| Service | Where to get |
|---------|-------------|
| Kimi K2.5 | [platform.moonshot.cn](https://platform.moonshot.cn) |
| Hermes Model | [openrouter.ai](https://openrouter.ai) |
| X/Twitter | [developer.x.com](https://developer.x.com) |

## 📡 API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/jobs` | Create new job |
| GET | `/api/jobs` | List all jobs |
| GET | `/api/jobs/{id}` | Get job details |
| POST | `/api/jobs/{id}/retry` | Retry failed job |
| DELETE | `/api/jobs/{id}` | Delete job |
| GET | `/api/jobs/stats/summary` | Job statistics |
| POST | `/api/agent/chat` | Chat with Hermes Agent |
| WS | `/ws/jobs/{id}` | Real-time job updates |
| GET | `/health` | Health check |

## 📦 Tech Stack

- **Backend**: Python 3.12 + FastAPI + SQLAlchemy (SQLite)
- **Frontend**: Next.js 15 + TypeScript
- **Agent**: Hermes 3 (Llama 3.1) via OpenRouter
- **AI**: Kimi K2.5 (Moonshot) + Whisper (OpenAI)
- **Video**: yt-dlp + FFmpeg
- **Deploy**: PM2 + Caddy (reverse proxy)

## 📄 License

Built for the Hermes Agent Creative Hackathon by Nous Research.
