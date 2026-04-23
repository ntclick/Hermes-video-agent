"""
Subtitle Service — Autonomous Content Bridge
Generates .srt and .ass subtitle files from translated segments.
"""
import logging
from pathlib import Path

from backend.config import get_settings

logger = logging.getLogger("content-bridge.subtitle")


def _format_srt_time(seconds: float) -> str:
    """Convert seconds to SRT timestamp format: HH:MM:SS,mmm"""
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    millis = int((seconds % 1) * 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


def _format_ass_time(seconds: float) -> str:
    """Convert seconds to ASS timestamp format: H:MM:SS.cc"""
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    centis = int((seconds % 1) * 100)
    return f"{hours}:{minutes:02d}:{secs:02d}.{centis:02d}"


def generate_srt(segments: list[dict], job_id: int) -> str:
    """
    Generate an SRT subtitle file.

    Args:
        segments: list of {"start": float, "end": float, "text": str}

    Returns:
        Path to the generated .srt file
    """
    settings = get_settings()
    srt_path = settings.subtitles_dir / f"job_{job_id}.srt"

    lines = []
    for i, seg in enumerate(segments, 1):
        start = _format_srt_time(seg["start"])
        end = _format_srt_time(seg["end"])
        text = seg["text"]

        lines.append(f"{i}")
        lines.append(f"{start} --> {end}")
        lines.append(text)
        lines.append("")  # Blank line between entries

    content = "\n".join(lines)
    srt_path.write_text(content, encoding="utf-8")

    logger.info(f"[Job {job_id}] SRT generated: {srt_path} ({len(segments)} entries)")
    return str(srt_path)


def generate_ass(segments: list[dict], job_id: int) -> str:
    """
    Generate an ASS subtitle file with styled formatting.
    Uses a modern, readable style with semi-transparent background.

    Returns:
        Path to the generated .ass file
    """
    settings = get_settings()
    ass_path = settings.subtitles_dir / f"job_{job_id}.ass"

    # ASS header with premium styling
    header = """[Script Info]
Title: Content Bridge Subtitles
ScriptType: v4.00+
PlayResX: 1920
PlayResY: 1080
WrapStyle: 0

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Arial,56,&H00FFFFFF,&H000000FF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,3,2,0,2,40,40,60,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

    events = []
    for seg in segments:
        start = _format_ass_time(seg["start"])
        end = _format_ass_time(seg["end"])
        # Replace literal newlines with ASS newline tag if present
        text = seg["text"].replace("\n", "\\N")
        events.append(f"Dialogue: 0,{start},{end},Default,,0,0,0,,{text}")

    content = header + "\n".join(events) + "\n"
    ass_path.write_text(content, encoding="utf-8")

    logger.info(f"[Job {job_id}] ASS generated: {ass_path} ({len(segments)} entries)")
    return str(ass_path)


def generate_dual_subtitles(
    translated_segments: list[dict],
    job_id: int,
) -> tuple[str, str]:
    """
    Generate both SRT and ASS files.
    If segments have 'original' field, creates dual-language ASS.

    Returns: (srt_path, ass_path)
    """
    srt_path = generate_srt(translated_segments, job_id)

    # For ASS, we only want the translated text. The user explicitly requested to remove the dual-language (original Chinese) text.
    ass_path = generate_ass(translated_segments, job_id)

    return srt_path, ass_path
