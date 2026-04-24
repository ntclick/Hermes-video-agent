import sys
import asyncio

# 1. Ép hệ thống dùng WindowsProactorEventLoopPolicy từ đầu.
# Playwright và FFMpeg BẮT BUỘC cần cái này để gọi subprocess trên Windows.
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

import uvicorn

if __name__ == "__main__":
    # 2. Khởi tạo cấu hình Uvicorn
    # Quan trọng: loop="none" ngăn Uvicorn không tự động đè lại Policy của chúng ta!
    config = uvicorn.Config(
        "backend.main:app",
        host="127.0.0.1",
        port=8002,
        loop="none",
        reload=False  # KHÔNG DÙNG RELOAD, vì reload sẽ tách process và xoá Policy
    )
    server = uvicorn.Server(config)
    print("Starting Windows Backend...")
    server.run()
