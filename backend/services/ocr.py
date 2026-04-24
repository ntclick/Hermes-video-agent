"""
OCR Service — Autonomous Content Bridge
Detects hardcoded text in video frames using EasyOCR,
translates via Kimi, and generates FFmpeg filters to blur + overlay.
"""
import asyncio
import logging
import json
import sys
import re
import tempfile
from pathlib import Path
from collections import defaultdict

logger = logging.getLogger("content-bridge.ocr")

# ── Font mapping per target language ────────────────────────────────
# Windows fonts
_WIN_FONTS = {
    "vi": "C\\:/Windows/Fonts/arial.ttf",          # Arial supports Vietnamese diacritics
    "en": "C\\:/Windows/Fonts/arial.ttf",
    "zh": "C\\:/Windows/Fonts/msyh.ttc",           # Microsoft YaHei — Chinese
    "ja": "C\\:/Windows/Fonts/YuGothR.ttc",        # Yu Gothic — Japanese
    "ko": "C\\:/Windows/Fonts/malgun.ttf",          # Malgun Gothic — Korean
}
# Linux fonts (install: apt install fonts-noto-cjk fonts-noto)
_LINUX_FONTS = {
    "vi": "/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf",
    "en": "/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf",
    "zh": "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "ja": "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "ko": "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
}


def _get_font_path(target_language: str) -> str:
    """Get the appropriate font path for the target language."""
    lang = target_language[:2].lower()
    if sys.platform == "win32":
        return _WIN_FONTS.get(lang, _WIN_FONTS["en"])
    else:
        return _LINUX_FONTS.get(lang, _LINUX_FONTS["en"])


# ── Lazy-loaded EasyOCR reader ──────────────────────────────────────
_reader = None

def _get_reader():
    global _reader
    if _reader is None:
        import easyocr
        logger.info("Loading EasyOCR models (ch_sim, en)...")
        _reader = easyocr.Reader(['ch_sim', 'en'], gpu=False)
        logger.info("EasyOCR loaded successfully.")
    return _reader


# ── Frame extraction ────────────────────────────────────────────────
async def _extract_frames(video_path: str, output_dir: Path, interval: int = 1) -> list[Path]:
    """Extract frames from video at every `interval` seconds."""
    output_dir.mkdir(parents=True, exist_ok=True)

    cmd = [
        "ffmpeg", "-y", "-i", video_path,
        "-vf", f"fps=1/{interval}",
        "-q:v", "2",
        str(output_dir / "frame_%04d.jpg")
    ]

    process = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await process.communicate()

    if process.returncode != 0:
        raise RuntimeError(f"FFmpeg frame extraction failed: {stderr.decode()[-300:]}")

    frames = sorted(output_dir.glob("frame_*.jpg"))
    logger.info(f"Extracted {len(frames)} frames (every {interval}s)")
    return frames


# ── OCR + Grouping ──────────────────────────────────────────────────
def _detect_text_regions(frames: list[Path], interval: int) -> list[dict]:
    """
    Run EasyOCR on sampled frames and group identical text across
    consecutive frames into time ranges.

    Returns list of:
        {"text": str, "x": int, "y": int, "w": int, "h": int,
         "t_start": float, "t_end": float}
    """
    reader = _get_reader()

    # raw_detections: list of (frame_time, text, x, y, w, h)
    raw = []
    # Get frame height from first frame to determine subtitle zone
    frame_h = 0
    if frames:
        from PIL import Image
        with Image.open(str(frames[0])) as img:
            frame_h = img.height
    subtitle_zone_y = int(frame_h * 0.75) if frame_h > 0 else 9999  # bottom 25% = subtitle area

    for i, frame_path in enumerate(frames):
        t = i * interval  # time in seconds
        results = reader.readtext(str(frame_path), detail=1)

        for bbox, text, confidence in results:
            if confidence < 0.50 or not text.strip():
                continue
            # Skip very short text (likely noise)
            text_clean = text.strip()
            if len(text_clean) < 2:
                continue

            tl, tr, br, bl = bbox
            x = int(min(tl[0], bl[0]))
            y = int(min(tl[1], tr[1]))
            w = int(max(tr[0], br[0]) - x)
            h = int(max(bl[1], br[1]) - y)

            # Skip tiny or huge boxes
            if w < 25 or h < 12 or w > 1600:
                continue

            # Skip text in the bottom 25% — that's our subtitle area, don't blur it
            if y > subtitle_zone_y:
                continue

            raw.append({
                "text": text_clean, "x": x, "y": y, "w": w, "h": h, "t": t
            })

    if not raw:
        return []

    # ── Group identical text at similar positions across frames ──
    # Key: (text, quantized_x, quantized_y) → merge into time ranges
    # Use tighter 20px grid to avoid merging different text blocks
    groups = defaultdict(list)
    for det in raw:
        qx = det["x"] // 20
        qy = det["y"] // 20
        key = (det["text"], qx, qy)
        groups[key].append(det)

    merged = []
    for key, dets in groups.items():
        times = [d["t"] for d in dets]
        # Average position across all frames
        avg_x = int(sum(d["x"] for d in dets) / len(dets))
        avg_y = int(sum(d["y"] for d in dets) / len(dets))
        max_w = max(d["w"] for d in dets)
        max_h = max(d["h"] for d in dets)

        merged.append({
            "text": dets[0]["text"],
            "x": avg_x, "y": avg_y, "w": max_w, "h": max_h,
            "t_start": max(0, min(times) - 0.3),
            "t_end": max(times) + interval + 0.3,
        })

    # Sort by time, limit to 60 regions max to prevent FFmpeg overload
    merged.sort(key=lambda r: (r["t_start"], r["y"]))
    if len(merged) > 60:
        # Keep the most prominent ones (longer duration = more important)
        merged.sort(key=lambda r: r["t_end"] - r["t_start"], reverse=True)
        merged = merged[:60]
        merged.sort(key=lambda r: (r["t_start"], r["y"]))

    logger.info(f"Grouped {len(raw)} raw detections into {len(merged)} text regions")
    return merged


# ── Translation ─────────────────────────────────────────────────────
async def _translate_texts(texts: list[str], target_language: str, job_id: int) -> dict[str, str]:
    """Batch translate unique text strings via Kimi."""
    from backend.config import get_settings
    settings = get_settings()

    unique = list(set(texts))
    if not unique:
        return {}

    translation_map = {}
    chunk_size = 30  # smaller chunks for better accuracy

    for i in range(0, len(unique), chunk_size):
        chunk = unique[i:i + chunk_size]
        # Map language code to full name
        _lang_names = {"vi": "Vietnamese", "en": "English", "zh": "Chinese", "ja": "Japanese", "ko": "Korean"}
        lang_name = _lang_names.get(target_language[:2], target_language)
        prompt = (
            f"Translate ALL of the following text snippets to {lang_name}. "
            f"These are hardcoded text overlays burned into a video — they include ingredient lists, "
            f"measurements (ml, g, etc.), step instructions, timestamps, captions, and decorative text. "
            f"IMPORTANT RULES:\n"
            f"1. Translate EVERY item — do NOT skip any\n"
            f"2. Keep numbers and units (200ml, 3g, etc.) as-is, only translate the words\n"
            f"3. For very short text (1-2 chars), still translate or transliterate\n"
            f"4. Return ONLY a JSON object: {{\"original\": \"translated\"}}\n\n"
            + json.dumps(chunk, ensure_ascii=False)
        )

        try:
            from openai import AsyncOpenAI
            client = AsyncOpenAI(api_key=settings.kimi_api_key, base_url=settings.kimi_base_url)

            response = await client.chat.completions.create(
                model="kimi-k2.6",
                messages=[
                    {"role": "system", "content": (
                        f"You are a professional Chinese-to-{lang_name} translator specialized in video content. "
                        f"You MUST translate every single text snippet given to you. Never skip any item. "
                        f"Return only valid JSON: {{\"original\": \"translated\"}}."
                    )},
                    {"role": "user", "content": prompt}
                ],
                extra_body={"thinking": {"type": "disabled"}},
                response_format={"type": "json_object"},
            )

            content = response.choices[0].message.content
            translated = json.loads(content)
            translation_map.update(translated)
            logger.info(f"[Job {job_id}] Translated OCR chunk: {len(translated)}/{len(chunk)} items")
            
            # Check for missing translations
            missing = [t for t in chunk if t not in translated]
            if missing:
                logger.warning(f"[Job {job_id}] OCR: {len(missing)} texts not translated: {missing[:5]}")
        except Exception as e:
            logger.error(f"[Job {job_id}] OCR translation chunk failed: {e}")
            for t in chunk:
                translation_map[t] = t  # fallback: keep original

    return translation_map


# ── FFmpeg filter generation ────────────────────────────────────────
def _escape_ffmpeg_text(text: str) -> str:
    """Escape special characters for FFmpeg drawtext filter."""
    # FFmpeg drawtext escaping rules
    text = text.replace("\\", "\\\\\\\\")
    text = text.replace("'", "\u2019")  # replace apostrophe with unicode right single quote
    text = text.replace(":", "\\:")
    text = text.replace(",", "\\,")
    text = text.replace(";", "\\;")
    text = text.replace("[", "\\[")
    text = text.replace("]", "\\]")
    text = text.replace("%", "%%")
    return text


def _build_filters(regions: list[dict], translation_map: dict, target_language: str) -> list[str]:
    """
    Generate FFmpeg filter strings to BLUR (cover) all detected hardcoded text.
    
    Strategy: Only blur the original text — do NOT overlay translated text.
    The burned-in subtitles at the bottom already provide the translation.
    This avoids duplication, visual clutter, and misaligned text.
    
    Skips text in the bottom 20% of the frame (that's the subtitle area).
    """
    filters = []

    for region in regions:
        x, y, w, h = region["x"], region["y"], region["w"], region["h"]
        t_start, t_end = region["t_start"], region["t_end"]
        enable = f"between(t,{t_start:.1f},{t_end:.1f})"

        # Cover original text with a dark box (clean, reliable, no artifacts)
        x_pad = max(0, x - 6)
        y_pad = max(0, y - 4)
        w_pad = w + 12
        h_pad = h + 8
        filters.append(
            f"drawbox=x={x_pad}:y={y_pad}:w={w_pad}:h={h_pad}:"
            f"color=black@0.85:t=fill:enable='{enable}'"
        )

    return filters


# ── Main entry point ────────────────────────────────────────────────
async def process_video_ocr(
    video_path: str,
    target_language: str,
    job_id: int,
    progress_callback=None,
) -> list[str]:
    """
    Full OCR pipeline:
    1. Extract frames (every 2s)
    2. Detect text regions with EasyOCR
    3. Group identical text across frames
    4. Generate FFmpeg drawbox filters to blur/cover detected text

    Note: No translation is done here — the burned-in subtitles handle translation.
    OCR only removes the original hardcoded text to keep the video clean.

    Returns: list of FFmpeg filter strings
    """
    logger.info(f"[Job {job_id}] Starting OCR Blur Pipeline")

    # Step 1: Extract frames (every 1s for better coverage)
    temp_dir = Path(tempfile.mkdtemp(prefix=f"ocr_job_{job_id}_"))
    interval = 1  # 1 second between frames
    try:
        frames = await _extract_frames(video_path, temp_dir, interval=interval)

        if progress_callback:
            await progress_callback(10.0, f"Extracted {len(frames)} frames for OCR")

        if not frames:
            logger.warning(f"[Job {job_id}] No frames extracted, skipping OCR")
            return []

        # Step 2: OCR detection (CPU-heavy, run in thread)
        if progress_callback:
            await progress_callback(15.0, "Running EasyOCR detection...")

        regions = await asyncio.get_event_loop().run_in_executor(
            None, _detect_text_regions, frames, interval
        )

        if progress_callback:
            await progress_callback(60.0, f"Detected {len(regions)} text regions")

        if not regions:
            logger.info(f"[Job {job_id}] No hardcoded text detected in video frames")
            return []

        # Step 3: Build blur filters (no translation needed — subtitles handle that)
        if progress_callback:
            await progress_callback(80.0, "Generating blur filters...")

        filters = _build_filters(regions, {}, target_language)

        logger.info(f"[Job {job_id}] OCR blur pipeline complete: {len(filters)} filters generated")

        if progress_callback:
            await progress_callback(100.0, f"OCR done: {len(filters)} blur filters ready")

        return filters

    finally:
        # Cleanup temp frames
        try:
            import shutil
            shutil.rmtree(temp_dir)
        except Exception:
            pass
