import asyncio
import logging
import json
import math
import tempfile
import cv2
import easyocr
from pathlib import Path

from backend.config import get_settings
from backend.agent.tools import execute_tool

logger = logging.getLogger("content-bridge.ocr")

# Lazy load the reader to avoid memory overhead when not used
_reader = None

def get_reader():
    global _reader
    if _reader is None:
        logger.info("Loading EasyOCR models (ch_sim, en)...")
        _reader = easyocr.Reader(['ch_sim', 'en'], gpu=True) # Will fallback to CPU if no GPU
    return _reader

async def extract_frames_for_ocr(video_path: str, output_dir: Path, fps: int = 1) -> list[Path]:
    """Extract frames from the video at a specific fps."""
    output_dir.mkdir(parents=True, exist_ok=True)
    
    cmd = [
        "ffmpeg", "-y", "-i", video_path,
        "-vf", f"fps={fps}",
        "-frame_pts", "1", # Name files by their timestamp in milliseconds/frames
        "-q:v", "2",
        str(output_dir / "%05d.jpg")
    ]
    
    logger.info(f"Extracting frames for OCR at {fps} fps...")
    process = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await process.communicate()
    
    if process.returncode != 0:
        logger.error(f"FFmpeg frame extraction failed: {stderr.decode()}")
        raise RuntimeError("Failed to extract frames for OCR")
        
    frames = sorted(list(output_dir.glob("*.jpg")))
    logger.info(f"Extracted {len(frames)} frames for OCR processing.")
    return frames

async def process_video_ocr(video_path: str, target_language: str, job_id: int, progress_callback=None) -> list[str]:
    """
    1. Extract frames
    2. Detect Chinese text boxes
    3. Translate unique texts
    4. Generate FFmpeg filter strings (delogo + drawtext)
    """
    logger.info(f"[Job {job_id}] Starting OCR Translation Pipeline")
    settings = get_settings()
    
    # We will use a temporary directory for frames
    temp_dir = Path(tempfile.mkdtemp(prefix=f"ocr_job_{job_id}_"))
    frames = await extract_frames_for_ocr(video_path, temp_dir, fps=1)
    
    if progress_callback:
        await progress_callback(5.0, "Frames extracted. Starting OCR detection...")
        
    reader = get_reader()
    
    # Data structure to hold detections
    # { frame_idx: [ {"text": "...", "bbox": (x, y, w, h), "conf": 0.9} ] }
    all_detections = {}
    unique_texts = set()
    
    # --- STEP 1: OCR Detection ---
    # We run OCR on each frame. This is CPU intensive.
    total_frames = len(frames)
    for i, frame_path in enumerate(frames):
        # frame_idx is in seconds because fps=1
        frame_idx = int(frame_path.stem) - 1 # 1-indexed by ffmpeg usually, but %05d might start at 1
        
        # Read image
        result = reader.readtext(str(frame_path), detail=1)
        
        frame_detections = []
        for (bbox, text, prob) in result:
            if prob < 0.3:
                continue
                
            # bbox is a list of 4 points: [top-left, top-right, bottom-right, bottom-left]
            tl, tr, br, bl = bbox
            x = int(min(tl[0], bl[0]))
            y = int(min(tl[1], tr[1]))
            w = int(max(tr[0], br[0]) - x)
            h = int(max(bl[1], br[1]) - y)
            
            # Filter out very small boxes or full screen boxes
            if w < 20 or h < 10 or w > 1500:
                continue
                
            # Filter out pure numbers or English if we mainly want to translate Chinese
            # But let's keep it simple and translate everything.
            text = text.strip()
            if not text:
                continue
                
            frame_detections.append({
                "text": text,
                "x": x, "y": y, "w": w, "h": h
            })
            unique_texts.add(text)
            
        all_detections[frame_idx] = frame_detections
        
        if progress_callback and i % 5 == 0:
            await progress_callback(
                5.0 + (i / total_frames) * 45.0, 
                f"OCR Processing: {i}/{total_frames} frames"
            )
            
    # --- STEP 2: Translation ---
    if progress_callback:
        await progress_callback(50.0, f"Translating {len(unique_texts)} unique text blocks to {target_language}...")
        
    unique_texts_list = list(unique_texts)
    translation_map = {}
    
    if unique_texts_list:
        # We can batch translate using Kimi
        # Chunking if too many
        chunk_size = 50
        for i in range(0, len(unique_texts_list), chunk_size):
            chunk = unique_texts_list[i:i+chunk_size]
            prompt = f"Translate the following short video text snippets (like cooking ingredients or subtitles) from Chinese to {target_language}. Return a JSON object mapping the original text to the translated text. ONLY return the valid JSON object.\n\n"
            prompt += json.dumps(chunk, ensure_ascii=False)
            
            from openai import AsyncOpenAI
            client = AsyncOpenAI(api_key=settings.kimi_api_key, base_url=settings.kimi_base_url)
            
            try:
                response = await client.chat.completions.create(
                    model="kimi-k2.6",
                    messages=[
                        {"role": "system", "content": "You are a professional translator. Always return a valid JSON object map: {\"original\": \"translated\"}."},
                        {"role": "user", "content": prompt}
                    ],
                    extra_body={"thinking": {"type": "disabled"}},
                    response_format={"type": "json_object"}
                )
                
                content = response.choices[0].message.content
                translated_chunk = json.loads(content)
                translation_map.update(translated_chunk)
            except Exception as e:
                logger.error(f"Translation chunk failed: {e}")
                # Fallback: keep original
                for t in chunk:
                    translation_map[t] = t
                    
    # --- STEP 3: Generate FFmpeg Filters ---
    if progress_callback:
        await progress_callback(70.0, "Generating FFmpeg overlay filters...")
        
    filters = []
    
    # We will generate delogo and drawtext filters for each frame
    # Since fps=1, each frame represents exactly 1 second of video
    # between(t, start, end)
    
    for frame_idx, detections in all_detections.items():
        start_t = frame_idx
        end_t = frame_idx + 1
        
        for det in detections:
            x, y, w, h = det["x"], det["y"], det["w"], det["h"]
            original_text = det["text"]
            translated_text = translation_map.get(original_text, original_text)
            
            # Clean text for FFmpeg (escape colons, commas, quotes)
            safe_text = translated_text.replace("'", "").replace(":", "\\:").replace(",", "\\,")
            
            # 1. Delogo (Blur)
            # delogo requires width and height to be at least 1, and inside bounds
            # To avoid errors, pad w and h slightly but keep in bounds
            w_pad = max(1, w + 10)
            h_pad = max(1, h + 10)
            x_pad = max(0, x - 5)
            y_pad = max(0, y - 5)
            
            filters.append(f"delogo=x={x_pad}:y={y_pad}:w={w_pad}:h={h_pad}:enable='between(t,{start_t},{end_t})'")
            
            # 2. Drawtext
            # Use Arial or a generic sans-serif font
            font_size = max(12, int(h * 0.8)) # Scale font size relative to bounding box
            # We add a semi-transparent black background box just in case delogo isn't clean enough
            drawtext_filter = (
                f"drawtext=text='{safe_text}':"
                f"fontcolor=white:fontsize={font_size}:"
                f"box=1:boxcolor=black@0.6:boxborderw=5:"
                f"x={x}:y={y}:"
                f"enable='between(t,{start_t},{end_t})'"
            )
            filters.append(drawtext_filter)
            
    # Cleanup temp dir
    try:
        import shutil
        shutil.rmtree(temp_dir)
    except Exception:
        pass
        
    logger.info(f"[Job {job_id}] OCR Pipeline finished. Generated {len(filters)} filters.")
    return filters
