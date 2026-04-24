import asyncio, sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

engine = create_async_engine("sqlite+aiosqlite:///F:/Work/Tools/video hermes/content-bridge/data/content_bridge.db")

async def main():
    Session = sessionmaker(engine, class_=AsyncSession)
    async with Session() as s:
        r = await s.execute(text('SELECT id, error_message, logs FROM jobs ORDER BY id DESC LIMIT 2'))
        for row in r.fetchall():
            print(f"=== Job {row[0]} ===")
            print(f"Error: {row[1]}")
            if row[2]:
                print(f"Logs (tail): ...{row[2][-800:]}")
            print()

asyncio.run(main())
