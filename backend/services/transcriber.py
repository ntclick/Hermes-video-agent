"""
Transcriber Service — Autonomous Content Bridge
Extracts audio from video, then uses Whisper for speech-to-text.
"""
import asyncio
import logging
from pathlib import Path

from backend.config import get_settings

logger = logging.getLogger("content-bridge.transcriber")

# Lazy-load whisper to avoid slow import at startup
_whisper_model = None


def _get_whisper_model():
    """Load Whisper model lazily (first call takes time)."""
    global _whisper_model
    if _whisper_model is None:
        import whisper
        settings = get_settings()
        model_name = settings.whisper_model
        logger.info(f"Loading Whisper model: {model_name}")
        _whisper_model = whisper.load_model(model_name)
        logger.info(f"Whisper model '{model_name}' loaded successfully")
    return _whisper_model


async def extract_audio(video_path: str, job_id: int) -> str:
    """
    Extract audio track from video using FFmpeg.

    Returns: path to extracted audio file (.wav)
    """
    settings = get_settings()
    audio_dir = settings.downloads_dir / str(job_id)
    audio_dir.mkdir(parents=True, exist_ok=True)
    audio_path = str(audio_dir / "audio.wav")

    logger.info(f"[Job {job_id}] Extracting audio from {video_path}")

    cmd = [
        "ffmpeg", "-y",
        "-i", video_path,
        "-vn",                    # No video
        "-acodec", "pcm_s16le",   # PCM 16-bit
        "-ar", "16000",           # 16kHz sample rate (optimal for Whisper)
        "-ac", "1",               # Mono
        audio_path,
    ]

    process = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await process.communicate()

    if process.returncode != 0:
        error = stderr.decode("utf-8", errors="replace")
        logger.error(f"[Job {job_id}] FFmpeg audio extraction failed: {error}")
        raise RuntimeError(f"Audio extraction failed: {error[:500]}")

    logger.info(f"[Job {job_id}] Audio extracted: {audio_path}")
    return audio_path


async def transcribe_audio(audio_path: str, job_id: int) -> list[dict]:
    """
    Transcribe audio using Whisper (runs in thread pool because Whisper is sync).

    Returns: list of segments, each with:
        {
            "start": float (seconds),
            "end": float (seconds),
            "text": str
        }
    """
    logger.info(f"[Job {job_id}] Starting transcription with Whisper...")

    def _transcribe():
        import torch
        use_gpu = torch.cuda.is_available()
        model = _get_whisper_model()
        logger.info(f"[Job {job_id}] Whisper using GPU: {use_gpu}")
        result = model.transcribe(
            audio_path,
            task="transcribe",        # Transcribe, not translate
            verbose=False,
            word_timestamps=False,
            fp16=use_gpu,             # Use FP16 if GPU, FP32 if CPU
        )
        return result

    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(None, _transcribe)

    segments = []
    for seg in result.get("segments", []):
        segments.append({
            "start": round(seg["start"], 2),
            "end": round(seg["end"], 2),
            "text": seg["text"].strip(),
        })

    detected_lang = result.get("language", "unknown")
    total_text = " ".join(s["text"] for s in segments)
    logger.info(
        f"[Job {job_id}] Transcription complete: "
        f"{len(segments)} segments, language={detected_lang}, "
        f"{len(total_text)} chars"
    )

    return segments


async def full_transcribe(video_path: str, job_id: int) -> tuple[str, list[dict]]:
    """
    Full pipeline: extract audio → transcribe.

    Returns: (audio_path, segments)
    """
    audio_path = await extract_audio(video_path, job_id)
    segments = await transcribe_audio(audio_path, job_id)
    return audio_path, segments
