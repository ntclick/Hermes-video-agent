@echo off
setlocal
echo ===================================================
echo   Hermes Video Agent - Local Starter (Windows)
echo ===================================================

:: Check for FFmpeg
where ffmpeg >nul 2>nul
if %errorlevel% neq 0 (
    if not exist "%~dp0ffmpeg.exe" (
        echo [ERROR] FFmpeg is missing! 
        echo Please download FFmpeg: https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-win64-gpl.zip
        echo Extract the zip and put "ffmpeg.exe" and "ffprobe.exe" in this folder: %~dp0
        echo.
        pause
        exit /b 1
    )
    echo [INFO] Using local FFmpeg in project folder.
    set "PATH=%~dp0;%PATH%"
) else (
    echo [INFO] FFmpeg found in system PATH.
)

:: Check Python
set PYTHON_EXE=C:\Users\1phut\AppData\Local\Programs\Python\Python313\python.exe
if not exist "%PYTHON_EXE%" (
    set PYTHON_EXE=python
)

:: Setup VENV
if not exist "venv\Scripts\activate.bat" (
    echo [INFO] Creating Python virtual environment...
    "%PYTHON_EXE%" -m venv venv
)

echo [INFO] Installing Backend dependencies...
call venv\Scripts\pip install -r requirements.txt
:: Install torch, torchvision, easyocr manually since they aren't in requirements.txt
call venv\Scripts\pip install torch torchvision torchaudio easyocr opencv-python

:: Ensure .env exists
if not exist ".env" (
    echo [INFO] Copying .env.example to .env
    copy .env.example .env
)

:: Start Backend in a new window
echo [INFO] Starting FastAPI Backend...
start "Hermes Backend API" cmd /c "call venv\Scripts\activate && set PYTHONUTF8=1 && set PYTHONIOENCODING=utf-8 && uvicorn backend.main:app --host 127.0.0.1 --port 8000 --reload"


:: Setup and Start Frontend
echo [INFO] Installing Frontend dependencies...
cd frontend
if not exist "node_modules" (
    call npm install
)

:: Ensure Frontend points to local backend
if not exist ".env.local" (
    echo NEXT_PUBLIC_API_URL=http://localhost:8000> .env.local
)

echo [INFO] Starting Next.js Frontend...
call npm run dev
