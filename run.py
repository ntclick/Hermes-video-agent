"""
run.py - Launcher for Windows dev environment.
Sets ProactorEventLoop BEFORE uvicorn starts to fix NotImplementedError
with Playwright and asyncio.create_subprocess_exec on Windows.
"""
import sys
import asyncio

# MUST be set before uvicorn imports anything
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

import uvicorn

if __name__ == "__main__":
    uvicorn.run(
        "backend.main:app",
        host="127.0.0.1",
        port=8000,
        reload=True,
        loop="asyncio",  # Force asyncio loop (picks up ProactorEventLoopPolicy on Windows)
    )
