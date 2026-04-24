import asyncio
import sys
from backend.services.downloader import download_video
from backend.config import get_settings

async def test():
    try:
        res = await download_video("https://www.douyin.com/jingxuan?modal_id=7619259744494177570", 1)
        print("Success:", res)
    except Exception as e:
        print("Exception type:", type(e))
        import traceback
        traceback.print_exc()

asyncio.run(test())
