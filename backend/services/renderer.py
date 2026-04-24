"""
Renderer Service — Autonomous Content Bridge
Uses FFmpeg to burn subtitles into video and optimize for Twitter.
"""
import asyncio
import logging
import os
import sys
import tempfile as _tmpfile
from pathlib import Path

from backend.config import get_settings

logger = logging.getLogger("content-bridge.renderer")

# Twitter video limits
TWITTER_MAX_DURATION = 140  # seconds
TWITTER_MAX_SIZE_MB = 512

_has_nvenc = None

def _check_nvenc():
    """Check if FFmpeg has NVIDIA GPU encoding support (h264_nvenc)."""
    global _has_nvenc
    if _has_nvenc is None:
        import subprocess
        try:
            res = subprocess.run(
                ["ffmpeg", "-hide_banner", "-encoders"],
                capture_output=True, text=True, check=False
            )
            _has_nvenc = "h264_nvenc" in res.stdout
            if _has_nvenc:
                logger.info("FFmpeg NVENC (GPU Encoding) is AVAILABLE.")
            else:
                logger.info("FFmpeg NVENC is NOT available. Falling back to CPU.")
        except Exception:
            _has_nvenc = False
    return _has_nvenc

async def _get_video_dimensions(video_path: str) -> tuple[int, int] | None:
    """Get video width and height using ffprobe."""
    cmd = [
        "ffprobe", "-v", "error",
        "-select_streams", "v:0",
        "-show_entries", "stream=width,height",
        "-of", "csv=p=0:s=x",
        video_path,
    ]
    process = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    stdout, _ = await process.communicate()
    try:
        w, h = stdout.decode().strip().split("x")
        return int(w), int(h)
    except Exception:
        return None


async def _get_duration(video_path: str) -> float | None:
    """Get video duration in seconds using ffprobe."""
    cmd = [
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        video_path,
    ]
    process = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    stdout, _ = await process.communicate()
    try:
        return float(stdout.decode().strip())
    except (ValueError, AttributeError):
        return None


def _validate_ocr_filters(filters: list[str], vid_w: int, vid_h: int) -> list[str]:
    """
    Validate and fix delogo filters to ensure coordinates are within video bounds.
    Remove any filters that can't be fixed.
    """
    import re
    valid = []
    for f in filters:
        if f.startswith("delogo="):
            # Extract x, y, w, h from delogo filter
            m = re.search(r'x=(\d+):y=(\d+):w=(\d+):h=(\d+)', f)
            if m:
                x, y, w, h = int(m.group(1)), int(m.group(2)), int(m.group(3)), int(m.group(4))
                # Clamp to video bounds
                x = max(0, min(x, vid_w - 2))
                y = max(0, min(y, vid_h - 2))
                w = max(1, min(w, vid_w - x))
                h = max(1, min(h, vid_h - y))
                # Replace with clamped values
                f = re.sub(r'x=\d+', f'x={x}', f, count=1)
                f = re.sub(r'y=\d+', f'y={y}', f, count=1)
                f = re.sub(r'w=\d+', f'w={w}', f, count=1)
                f = re.sub(r'h=\d+', f'h={h}', f, count=1)
            valid.append(f)
        elif f.startswith("drawtext="):
            valid.append(f)
        else:
            valid.append(f)
    return valid


async def _validate_video(video_path: str) -> tuple[bool, str]:
    """Verify the file is a decodable video with at least one video stream."""
    if not os.path.exists(video_path):
        return False, "File does not exist"
    size = os.path.getsize(video_path)
    if size < 10_000:  # <10KB is definitely not a real video
        return False, f"File too small ({size} bytes) — likely a corrupt or partial download"
    cmd = [
        "ffprobe", "-v", "error",
        "-select_streams", "v:0",
        "-show_entries", "stream=codec_name,width,height,duration",
        "-of", "compact=p=0",
        video_path,
    ]
    proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    stdout, stderr = await proc.communicate()
    if proc.returncode != 0:
        err = stderr.decode("utf-8", errors="replace")
        return False, f"ffprobe failed: {err[:300]}"
    if not stdout.decode().strip():
        return False, "No video stream found in file"
    return True, ""


async def render_video(
    video_path: str,
    subtitle_path: str,
    job_id: int,
    optimize_for_twitter: bool = True,
    ocr_filters: list[str] = None,
) -> str:
    """
    Burn subtitles into video using FFmpeg.
    If OCR filters cause rendering to fail, automatically retries without them.
    """
    settings = get_settings()
    output_dir = settings.processed_dir / str(job_id)
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = str(output_dir / "output.mp4")

    logger.info(f"[Job {job_id}] Rendering video with subtitles...")

    # Pre-flight: validate input video before wasting time on FFmpeg
    valid, val_err = await _validate_video(video_path)
    if not valid:
        raise RuntimeError(f"Input video invalid, cannot render: {val_err}")

    # Get video dimensions for OCR filter validation
    if ocr_filters:
        dims = await _get_video_dimensions(video_path)
        if dims:
            vid_w, vid_h = dims
            logger.info(f"[Job {job_id}] Video dimensions: {vid_w}x{vid_h}")
            ocr_filters = _validate_ocr_filters(ocr_filters, vid_w, vid_h)
        else:
            logger.warning(f"[Job {job_id}] Could not get video dimensions, skipping OCR filter validation")

    # Build subtitle filter
    sub_filter = ""
    if subtitle_path:
        sub_ext = Path(subtitle_path).suffix.lower()
        ff_subtitle_path = subtitle_path
        if sys.platform == "win32":
            ff_subtitle_path = ff_subtitle_path.replace('\\', '/').replace(':', '\\:')

        if sub_ext == ".ass":
            mask_filter = "drawbox=y=ih-ih*0.18:color=black@0.75:width=iw:height=ih*0.18:t=fill"
            sub_filter = f"{mask_filter},ass='{ff_subtitle_path}'"
        else:
            sub_filter = f"subtitles='{ff_subtitle_path}':force_style='FontSize=24,PrimaryColour=&H00FFFFFF,OutlineColour=&H00000000,Outline=2,Shadow=0,MarginV=40'"

    # Try rendering with OCR filters first, fallback without if it fails
    result, last_error = await _do_render(
        video_path, output_path, output_dir, sub_filter,
        job_id, optimize_for_twitter, ocr_filters
    )

    if result is None and ocr_filters:
        logger.warning(f"[Job {job_id}] Render with OCR filters failed, retrying WITHOUT OCR overlay...")
        result, last_error = await _do_render(
            video_path, output_path, output_dir, sub_filter,
            job_id, optimize_for_twitter, None  # No OCR filters
        )

    if result is None:
        raise RuntimeError(f"Video rendering failed (FFmpeg error): {last_error[-600:]}")

    # Check output file
    output_size_mb = os.path.getsize(result) / (1024 * 1024)
    logger.info(f"[Job {job_id}] Render complete: {result} ({output_size_mb:.1f} MB)")

    if optimize_for_twitter and output_size_mb > TWITTER_MAX_SIZE_MB:
        logger.warning(
            f"[Job {job_id}] Output too large for Twitter ({output_size_mb:.1f}MB). "
            f"Re-encoding with lower quality..."
        )
        result = await _reencode_smaller(video_path, subtitle_path, job_id, sub_filter)

    return result


async def _has_audio_stream(video_path: str) -> bool:
    """Check if video has at least one audio stream."""
    cmd = [
        "ffprobe", "-v", "error",
        "-select_streams", "a:0",
        "-show_entries", "stream=codec_type",
        "-of", "csv=p=0",
        video_path,
    ]
    process = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    stdout, _ = await process.communicate()
    return bool(stdout.decode().strip())


async def _do_render(
    video_path: str,
    output_path: str,
    output_dir: Path,
    sub_filter: str,
    job_id: int,
    optimize_for_twitter: bool,
    ocr_filters: list[str] | None,
) -> tuple[str | None, str]:
    """
    Execute a single FFmpeg render attempt.
    Returns (output_path, "") on success, (None, ffmpeg_stderr) on failure.
    """
    # Build full filter chain
    if ocr_filters and sub_filter:
        ocr_chain = ",".join(ocr_filters)
        full_filter = f"{ocr_chain},{sub_filter}"
    elif ocr_filters:
        full_filter = ",".join(ocr_filters)
    elif sub_filter:
        full_filter = sub_filter
    else:
        full_filter = ""

    # If filter chain is long, write to script file
    filter_script_path = None
    use_script = len(full_filter) > 2000

    if use_script:
        fd = _tmpfile.NamedTemporaryFile(
            mode='w', suffix='.txt', prefix='ffmpeg_filter_',
            dir=str(output_dir), delete=False, encoding='utf-8'
        )
        filter_script_path = fd.name
        fd.write(full_filter)
        fd.close()
        logger.info(f"[Job {job_id}] Filter chain ({len(full_filter)} chars) written to script: {filter_script_path}")

    # Build command
    cmd = ["ffmpeg", "-y", "-i", video_path]

    if use_script:
        cmd.extend(["-filter_script:v", filter_script_path])
    elif full_filter:
        cmd.extend(["-vf", full_filter])

    has_audio = await _has_audio_stream(video_path)
    if not has_audio:
        logger.info(f"[Job {job_id}] No audio stream detected — skipping audio encoding")

    if _check_nvenc():
        cmd.extend(["-c:v", "h264_nvenc", "-preset", "p4", "-cq", "23"])
    else:
        cmd.extend(["-c:v", "libx264", "-preset", "fast", "-crf", "23"])

    if has_audio:
        cmd.extend(["-c:a", "aac", "-b:a", "128k"])
    else:
        cmd.append("-an")

    cmd.extend(["-movflags", "+faststart"])

    if optimize_for_twitter:
        duration = await _get_duration(video_path)
        if duration and duration > TWITTER_MAX_DURATION:
            logger.warning(f"[Job {job_id}] Trimming to {TWITTER_MAX_DURATION}s for Twitter")
            cmd.extend(["-t", str(TWITTER_MAX_DURATION)])
        cmd.extend(["-maxrate", "5M", "-bufsize", "10M"])

    cmd.append(output_path)

    label = "with OCR" if ocr_filters else "subtitles only"
    logger.info(f"[Job {job_id}] FFmpeg render ({label}): {' '.join(cmd[:6])}...")

    process = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await process.communicate()

    # Cleanup filter script
    if filter_script_path:
        try:
            os.unlink(filter_script_path)
        except Exception:
            pass

    if process.returncode != 0:
        error = stderr.decode("utf-8", errors="replace")
        logger.error(f"[Job {job_id}] FFmpeg render failed ({label}):\n{error[-1500:]}")
        return None, error[-1500:]

    if not os.path.exists(output_path) or os.path.getsize(output_path) == 0:
        logger.error(f"[Job {job_id}] Output file missing or empty after render")
        return None, "Output file missing or empty after render"

    return output_path, ""


async def _reencode_smaller(
    video_path: str, subtitle_path: str, job_id: int, sub_filter: str
) -> str:
    """Re-encode with lower quality to fit Twitter size limit."""
    settings = get_settings()
    output_path = str(settings.processed_dir / str(job_id) / "output_compressed.mp4")

    if _check_nvenc():
        cmd = [
            "ffmpeg", "-y",
            "-i", video_path,
            "-vf", f"scale='min(720,iw)':-2,{sub_filter}",
            "-c:v", "h264_nvenc",
            "-preset", "p4",
            "-cq", "28",
            "-c:a", "aac",
            "-b:a", "96k",
            "-maxrate", "2M",
            "-bufsize", "4M",
            "-t", str(TWITTER_MAX_DURATION),
            "-movflags", "+faststart",
            output_path,
        ]
    else:
        cmd = [
            "ffmpeg", "-y",
            "-i", video_path,
            "-vf", f"scale='min(720,iw)':-2,{sub_filter}",
            "-c:v", "libx264",
            "-preset", "medium",
            "-crf", "28",
            "-c:a", "aac",
            "-b:a", "96k",
            "-maxrate", "2M",
            "-bufsize", "4M",
            "-t", str(TWITTER_MAX_DURATION),
            "-movflags", "+faststart",
            output_path,
        ]

    process = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    _, stderr = await process.communicate()

    if process.returncode != 0:
        error = stderr.decode("utf-8", errors="replace")
        raise RuntimeError(f"Re-encode failed: {error[-500:]}")

    logger.info(f"[Job {job_id}] Re-encoded to smaller size: {output_path}")
    return output_path
