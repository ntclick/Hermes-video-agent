"""
Cover Video Composer — Autonomous Content Bridge
Uses FFmpeg to compose AI-generated scene images into a slideshow video
with Ken Burns effects, original audio, and burned subtitles.
"""
import asyncio
import logging
import os
from pathlib import Path

from backend.config import get_settings

logger = logging.getLogger("content-bridge.cover_composer")


async def compose_cover_video(
    scenes_dir: str,
    audio_path: str,
    subtitle_path: str | None,
    job_id: int,
    scene_duration: float = 5.0,
) -> str:
    """
    Compose a cover video from AI-generated scene images.
    
    Each image is shown for `scene_duration` seconds with Ken Burns
    zoom/pan effects. Original audio is overlaid and subtitles burned in.
    
    Args:
        scenes_dir: Directory containing scene_XX.jpg files
        audio_path: Path to original video audio track
        subtitle_path: ASS/SRT subtitle file (optional)
        job_id: Job identifier
        scene_duration: Duration per scene in seconds
    
    Returns:
        Path to the output cover video
    """
    settings = get_settings()
    output_dir = Path(settings.data_dir) / "processed" / str(job_id)
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = str(output_dir / "cover_output.mp4")

    scenes_path = Path(scenes_dir)
    images = sorted(scenes_path.glob("scene_*.jpg"))
    
    if not images:
        raise ValueError(f"No scene images found in {scenes_dir}")

    logger.info(f"[Job {job_id}] Composing cover video from {len(images)} scenes ({scene_duration}s each)...")

    # Build FFmpeg filter for Ken Burns effect slideshow
    # Each image gets a zoompan filter with slight zoom and pan
    total_duration = len(images) * scene_duration
    fps = 25
    frames_per_scene = int(scene_duration * fps)

    # Create a concat input file for FFmpeg
    concat_file = output_dir / "concat_scenes.txt"
    filter_inputs = []
    filter_chains = []

    for i, img in enumerate(images):
        filter_inputs.extend(["-loop", "1", "-t", str(scene_duration), "-i", str(img)])
        # Ken Burns: alternate between zoom-in and zoom-out with slight panning
        if i % 2 == 0:
            # Zoom in from 100% to 115%, pan slightly right
            zoompan = (
                f"[{i}:v]scale=1920:1080:force_original_aspect_ratio=increase,"
                f"crop=1920:1080,"
                f"zoompan=z='min(zoom+0.0012,1.15)':x='iw/2-(iw/zoom/2)+((iw/zoom/2)*0.1*(on/{frames_per_scene}))'"
                f":y='ih/2-(ih/zoom/2)':d={frames_per_scene}:s=1920x1080:fps={fps}[v{i}]"
            )
        else:
            # Zoom out from 115% to 100%, pan slightly left
            zoompan = (
                f"[{i}:v]scale=1920:1080:force_original_aspect_ratio=increase,"
                f"crop=1920:1080,"
                f"zoompan=z='if(eq(on,1),1.15,max(zoom-0.0012,1.0))':x='iw/2-(iw/zoom/2)-((iw/zoom/2)*0.1*(on/{frames_per_scene}))'"
                f":y='ih/2-(ih/zoom/2)':d={frames_per_scene}:s=1920x1080:fps={fps}[v{i}]"
            )
        filter_chains.append(zoompan)

    # Concat all video streams
    concat_inputs = "".join(f"[v{i}]" for i in range(len(images)))
    filter_chains.append(f"{concat_inputs}concat=n={len(images)}:v=1:a=0[vout]")

    # Add subtitle burning if available
    if subtitle_path and Path(subtitle_path).exists():
        sub_ext = Path(subtitle_path).suffix.lower()
        if sub_ext == ".ass":
            filter_chains.append(f"[vout]ass='{subtitle_path}'[vfinal]")
        else:
            filter_chains.append(f"[vout]subtitles='{subtitle_path}'[vfinal]")
        map_video = "[vfinal]"
    else:
        map_video = "[vout]"

    filter_complex = ";".join(filter_chains)

    # Build final command
    cmd = ["ffmpeg", "-y"]
    cmd.extend(filter_inputs)

    # Add audio input
    audio_idx = len(images)
    cmd.extend(["-i", audio_path])

    cmd.extend([
        "-filter_complex", filter_complex,
        "-map", map_video,
        "-map", f"{audio_idx}:a?",
        "-c:v", "libx264",
        "-preset", "fast",
        "-crf", "20",
        "-c:a", "aac",
        "-b:a", "128k",
        "-shortest",
        "-movflags", "+faststart",
        output_path,
    ])

    logger.info(f"[Job {job_id}] Running FFmpeg cover composition ({len(images)} scenes × {scene_duration}s)...")

    process = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await process.communicate()

    if process.returncode != 0:
        error = stderr.decode("utf-8", errors="replace")
        logger.error(f"[Job {job_id}] Cover composition failed: {error[-800:]}")
        raise RuntimeError(f"Cover video composition failed: {error[-500:]}")

    size_mb = os.path.getsize(output_path) / (1024 * 1024)
    logger.info(f"[Job {job_id}] Cover video rendered: {output_path} ({size_mb:.1f}MB)")

    return output_path
