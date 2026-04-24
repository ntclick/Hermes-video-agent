import asyncio
from backend.workers.pipeline import run_pipeline
from backend.config import get_settings

async def main():
    print("Starting pipeline for Job 1...")
    await run_pipeline(1, auto_publish=False)
    print("Pipeline finished.")

if __name__ == "__main__":
    asyncio.run(main())
