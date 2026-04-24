"""
Main — Autonomous Content Bridge
FastAPI application entry point with WebSocket support for real-time updates.
"""
import sys
import asyncio

# Fix for "NotImplementedError" in asyncio.subprocess on Windows (Python 3.8+)
# Note: This is only needed for local Windows dev; VPS (Linux) handles this natively.
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

import json
import logging
import time
import shutil
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse

from backend.config import get_settings
from backend.database import init_db, close_db
from backend.api.jobs import router as jobs_router
from backend.api.settings import router as settings_router
from backend.workers.pipeline import register_ws, unregister_ws
from backend.agent.hermes_agent import HermesAgent

# ── Auto Cleanup Task ─────────────────────────────────────────
async def cleanup_old_files():
    """Background task to delete old video files (older than 24h) to save storage."""
    settings = get_settings()
    dirs_to_clean = [settings.downloads_dir, settings.processed_dir]
    
    while True:
        try:
            now = time.time()
            cutoff = now - (24 * 3600)  # 24 hours
            deleted_count = 0
            
            for directory in dirs_to_clean:
                if not directory.exists():
                    continue
                for item in directory.iterdir():
                    if item.is_dir():
                        # Check modification time of directory
                        stat = item.stat()
                        if stat.st_mtime < cutoff:
                            try:
                                shutil.rmtree(item)
                                deleted_count += 1
                            except Exception as e:
                                logger.error(f"Failed to delete {item}: {e}")
            
            if deleted_count > 0:
                logger.info(f"🧹 Cleanup: Deleted {deleted_count} old job directories.")
        except Exception as e:
            logger.error(f"Cleanup task error: {e}")
            
        await asyncio.sleep(6 * 3600)  # Run every 6 hours

# ── Logging Setup ──────────────────────────────────────────────
settings = get_settings()

logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s │ %(name)-30s │ %(levelname)-7s │ %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("content-bridge")


# ── Application Lifespan ──────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown events."""
    logger.info("🚀 Starting Autonomous Content Bridge...")
    await init_db()
    logger.info("✅ Database initialized")

    # Start cleanup background task
    cleanup_task = asyncio.create_task(cleanup_old_files())

    # Bootstrap .env if it doesn't exist yet (first run on Windows)
    from backend.api.settings import ENV_PATH
    if not ENV_PATH.exists():
        ENV_PATH.parent.mkdir(parents=True, exist_ok=True)
        ENV_PATH.write_text(
            "# Autonomous Content Bridge — API keys\n"
            "KIMI_API_KEY=\n"
            "KIMI_BASE_URL=https://api.moonshot.ai/v1\n"
            "HERMES_API_KEY=\n"
            "HERMES_BASE_URL=https://openrouter.ai/api/v1\n"
            "HERMES_MODEL=kimi-k2.6\n"
            "HERMES_PROVIDER=kimi\n"
            "FAL_API_KEY=\n"
            "DOUYIN_COOKIES=\n"
            "WHISPER_MODEL=base\n",
            encoding="utf-8",
        )
        logger.info(f"✅ Created blank .env at {ENV_PATH}")
    else:
        logger.info(f"✅ .env found at {ENV_PATH}")

    # Ensure data directories exist
    settings.downloads_dir
    settings.processed_dir
    settings.subtitles_dir
    settings.logs_dir
    logger.info("✅ Data directories ready")

    yield

    logger.info("🛑 Shutting down...")
    await close_db()
    logger.info("👋 Goodbye!")


# ── FastAPI App ───────────────────────────────────────────────
app = FastAPI(
    title="Autonomous Content Bridge",
    description=(
        "🌉 Hermes Agent Creative Hackathon — "
        "Auto-download, translate, subtitle, and publish videos to X"
    ),
    version="1.0.0",
    lifespan=lifespan,
)

# CORS — allow frontend on port 3000
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "https://content-bridge.socialflow.vn",
        "*",  # For development
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount API routes
app.include_router(jobs_router)
app.include_router(settings_router)

# Mount static files for video playback
app.mount("/api/videos", StaticFiles(directory=settings.processed_dir), name="videos")
app.mount("/api/downloads", StaticFiles(directory=settings.downloads_dir), name="downloads")


# ── Health Check ──────────────────────────────────────────────
@app.get("/health")
async def health_check():
    return {
        "status": "healthy",
        "service": "content-bridge",
        "version": "1.0.0",
    }


# ── WebSocket for Real-time Updates ──────────────────────────
@app.websocket("/ws/jobs/{job_id}")
async def websocket_job_updates(websocket: WebSocket, job_id: int):
    """WebSocket endpoint for real-time job progress updates."""
    await websocket.accept()
    register_ws(job_id, websocket)
    logger.info(f"WebSocket connected: job {job_id}")

    try:
        while True:
            # Keep connection alive, handle client messages
            data = await websocket.receive_text()
            # Client can send ping/pong
            if data == "ping":
                await websocket.send_text("pong")
    except WebSocketDisconnect:
        logger.info(f"WebSocket disconnected: job {job_id}")
    finally:
        unregister_ws(job_id, websocket)


@app.websocket("/ws/all")
async def websocket_all_updates(websocket: WebSocket):
    """WebSocket endpoint for all job updates (dashboard-wide)."""
    await websocket.accept()
    logger.info("WebSocket connected: all jobs")

    # Register for all jobs (use -1 as special key)
    register_ws(-1, websocket)

    try:
        while True:
            data = await websocket.receive_text()
            if data == "ping":
                await websocket.send_text("pong")
    except WebSocketDisconnect:
        logger.info("WebSocket disconnected: all jobs")
    finally:
        unregister_ws(-1, websocket)


# ── Agent Chat Endpoint ──────────────────────────────────────
from pydantic import BaseModel


class AgentChatRequest(BaseModel):
    message: str
    conversation_history: list[dict] | None = None


@app.post("/api/agent/chat")
async def agent_chat(body: AgentChatRequest):
    """Chat with the Hermes Agent — can trigger pipeline actions."""
    agent = HermesAgent()
    result = await agent.process_message(
        body.message,
        body.conversation_history,
    )
    return result


# ── Init Modules ──────────────────────────────────────────────
# Create __init__.py files for proper Python packaging
import pathlib

_project_root = pathlib.Path(__file__).resolve().parent.parent
for init_dir in ["backend", "backend/services", "backend/agent", "backend/api", "backend/workers"]:
    init_file = _project_root / init_dir / "__init__.py"
    init_file.parent.mkdir(parents=True, exist_ok=True)
    if not init_file.exists():
        init_file.write_text("")
