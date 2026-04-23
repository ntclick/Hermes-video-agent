"""
Vision Service — Autonomous Content Bridge
Uses FFmpeg to extract keyframes and Kimi AI to summarize the contents.
"""
import asyncio
import base64
import json
import logging
import os
from pathlib import Path
from openai import AsyncOpenAI

from backend.config import get_settings

logger = logging.getLogger("content-bridge.vision")


async def extract_keyframes(video_path: str, job_id: int, max_frames: int = 5) -> str:
    """
    Extract keyframes from a video based on scene changes.
    
    Args:
        video_path: Original video path
        job_id: Job identifier
        max_frames: Max frames to extract
        
    Returns:
        String relative path to frames directory (e.g., 'processed_dir/job_id/frames')
    """
    settings = get_settings()
    frames_dir = settings.processed_dir / str(job_id) / "frames"
    frames_dir.mkdir(parents=True, exist_ok=True)
    
    logger.info(f"[Job {job_id}] Extracting key scenes using FFmpeg...")
    
    # We use select='gt(scene,0.4)' or 'gt(scene,0.2)' depending on the input.
    # To strictly limit to 5 frames, we can just use a fixed fps (e.g. fps=1/10) 
    # instead of scene detection to guarantee coverage across the video, 
    # or use scene detection with a fallback.
    # A safe fallback is to extract 5 frames evenly spaced across the video.
    
    # Let's get video duration first to calculate interval
    duration = await _get_duration(video_path)
    if not duration or duration < 5:
        fps_filter = "fps=1" # short video, 1 frame per sec
    else:
        # e.g., duration 60s, max_frames 5 -> 1 frame every 12 seconds
        interval = duration / (max_frames + 1)
        fps_filter = f"fps=1/{interval:.2f}"

    # Extract frames
    cmd = [
        "ffmpeg", "-y",
        "-i", video_path,
        "-vf", f"{fps_filter},scale=640:-1",
        "-vframes", str(max_frames),
        "-q:v", "5",  # Average quality to save space
        str(frames_dir / "frame_%03d.jpg"),
    ]

    process = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await process.communicate()

    if process.returncode != 0:
        error = stderr.decode("utf-8", errors="replace")
        logger.error(f"[Job {job_id}] FFmpeg frame extraction failed: {error[-500:]}")
        raise RuntimeError(f"Frame extraction failed: {error[-500:]}")

    logger.info(f"[Job {job_id}] Keyframes extracted to {frames_dir}")
    return str(frames_dir)


async def summarize_multimodal(frames_dir: str, transcript: str, job_id: int) -> str:
    """
    Generate a video summary using Kimi 2.5 with vision (if supported) + transcript.
    """
    settings = get_settings()
    client = AsyncOpenAI(
        api_key=settings.kimi_api_key,
        base_url=settings.kimi_base_url,
        timeout=30.0,
    )
    
    # Collect frames
    frames_path = Path(frames_dir)
    images = []
    if frames_path.exists():
        for file in sorted(frames_path.glob("*.jpg")):
            try:
                with open(file, "rb") as f:
                    b64_img = base64.b64encode(f.read()).decode("utf-8")
                images.append(b64_img)
            except Exception as e:
                logger.warning(f"[Job {job_id}] Failed to read image {file}: {e}")

    logger.info(f"[Job {job_id}] Generating multimodal summary with {len(images)} images and transcript...")

    system_prompt = (
        "You are an AI assistant that explains what happens in a video. "
        "You will be given a few keyframes (images) from the video and the full spoken transcript (subtitles). "
        "Generate a cohesive, structured summary in Vietnamese summarizing what the video is about, "
        "the visual context (what is seen), and the main message. Keep it concise (1-2 paragraphs). "
        "Do not list the frames. Synthesize the multimodal information into a smooth summary."
    )
    
    # Prepare content
    content = [{"type": "text", "text": f"Here is the spoken transcript:\n{transcript}"}]
    
    for img_b64 in images:
        content.append({
            "type": "image_url",
            "image_url": {
                "url": f"data:image/jpeg;base64,{img_b64}"
            }
        })

    try:
        response = await client.chat.completions.create(
            model="kimi-k2.6",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": content},
            ],
            extra_body={"thinking": {"type": "disabled"}},
            max_tokens=600,
        )
        summary = response.choices[0].message.content.strip()
        logger.info(f"[Job {job_id}] Summary generated successfully.")
        return summary
    except Exception as e:
        logger.error(f"[Job {job_id}] Fallback to text-only summary due to vision API error: {e}")
        # Fallback to Text-Only if Moonshot rejects image parts natively on this model
        try:
            content_text_only = [{"type": "text", "text": f"Here is the spoken transcript:\n{transcript}"}]
            response = await client.chat.completions.create(
                model="kimi-k2.6",
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": content_text_only},
                ],
                extra_body={"thinking": {"type": "disabled"}},
                max_tokens=600,
            )
            summary = response.choices[0].message.content.strip()
            return summary
        except Exception as e_fallback:
            logger.error(f"[Job {job_id}] Text fallback summarizing failed: {e_fallback}")
            return f"Summarization failed: {str(e_fallback)}"


async def _get_duration(video_path: str) -> float | None:
    """Get video duration in seconds using ffprobe."""
    cmd = [
        "ffprobe",
        "-v", "error",
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
