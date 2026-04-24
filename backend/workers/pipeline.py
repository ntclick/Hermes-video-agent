"""
Pipeline Worker — Autonomous Content Bridge
Orchestrates the full video processing pipeline as a background task.
"""
import asyncio
import logging
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from backend.config import get_settings, get_job_settings
from backend.database import get_session_factory
from backend.models import Job, JobStatus, XAccount
from backend.services.downloader import download_video
from backend.services.transcriber import full_transcribe
from backend.services.translator import translate_segments, generate_tweet_text
from backend.services.subtitle import generate_dual_subtitles
from backend.services.renderer import render_video
from backend.services.publisher import publish_to_x
from backend.services.vision import summarize_multimodal, extract_keyframes, summarize_multimodal

logger = logging.getLogger("content-bridge.pipeline")

# Global dict to track active WebSocket connections per job
_ws_connections: dict[int, list] = {}

# Tracking for cancelled jobs to stop the pipeline
_cancelled_jobs: set[int] = set()

def cancel_job_pipeline(job_id: int):
    """Signal that a job should be cancelled."""
    _cancelled_jobs.add(job_id)

def is_job_cancelled(job_id: int) -> bool:
    """Check if a job has been cancelled."""
    return job_id in _cancelled_jobs


def register_ws(job_id: int, ws):
    """Register a WebSocket for real-time log streaming."""
    if job_id not in _ws_connections:
        _ws_connections[job_id] = []
    _ws_connections[job_id].append(ws)


def unregister_ws(job_id: int, ws):
    """Remove a WebSocket connection."""
    if job_id in _ws_connections:
        _ws_connections[job_id] = [w for w in _ws_connections[job_id] if w != ws]


async def _broadcast_update(job_id: int, data: dict):
    """Send real-time update to all WebSocket clients watching this job."""
    import json
    if job_id in _ws_connections:
        msg = json.dumps(data)
        dead = []
        for ws in _ws_connections[job_id]:
            try:
                await ws.send_text(msg)
            except Exception:
                dead.append(ws)
        for ws in dead:
            _ws_connections[job_id].remove(ws)


async def _update_job(
    session: AsyncSession,
    job: Job,
    status: JobStatus | None = None,
    progress: float | None = None,
    log_message: str | None = None,
    **kwargs,
):
    """Update job state and broadcast to WebSocket clients."""
    if status is not None:
        job.status = status
    if progress is not None:
        job.progress = progress
    if log_message:
        job.append_log(log_message)
        logger.info(f"[Job {job.id}] {log_message}")

    for key, value in kwargs.items():
        if hasattr(job, key):
            setattr(job, key, value)

    session.add(job)
    await session.commit()

    # Broadcast real-time update
    await _broadcast_update(job.id, {
        "type": "job_update",
        "job": job.to_dict(),
    })


async def run_pipeline(job_id: int, auto_publish: bool = True):
    """
    Execute the full video processing pipeline for a job.

    Steps:
    1. Download video (yt-dlp)
    2. Transcribe audio (Whisper)
    3. Translate (Kimi K2.5)
    4. Generate subtitles (SRT/ASS)
    5. Render video with subtitles (FFmpeg)
    6. Publish to X (Twitter)
    """
    factory = get_session_factory()
    
    # Ensure job is removed from cancelled set if it was there from a previous run
    if job_id in _cancelled_jobs:
        _cancelled_jobs.remove(job_id)

    async def check_cancellation(session, job):
        """Helper to check if job was cancelled and stop the pipeline."""
        if is_job_cancelled(job_id):
            await _update_job(session, job, status=JobStatus.CANCELLED, progress=job.progress, log_message="🛑 Job cancelled by user.")
            return True
        return False

    async with factory() as session:
        job = await session.get(Job, job_id)
        if not job:
            logger.error(f"Job {job_id} not found")
            return

        try:
            # Load settings with user-provided key overrides (BYOK)
            settings = get_job_settings(job.user_keys_json)

            # Check for initial cancellation
            if await check_cancellation(session, job): return

            # ── Agent Banner ──────────────────────────────────────────
            provider = (settings.hermes_provider or "openrouter").lower()
            provider_label = {
                "kimi": "Kimi K2.5 (Moonshot)",
                "openrouter": "OpenRouter",
                "custom": "Custom endpoint",
            }.get(provider, provider)
            await _update_job(
                session, job,
                log_message=(
                    f"🤖 [Hermes Agent] Booting orchestrator · provider={provider_label} · model={settings.hermes_model}"
                ),
            )
            await _update_job(
                session, job,
                log_message=(
                    f"🧠 [Hermes Agent] Plan: download_video → transcribe_video → translate_content"
                    f" → summarize_multimodal → generate_subtitles → render_video"
                    + (" → publish_to_x" if auto_publish else " (auto_publish=off)")
                ),
            )

            # ── Step 1: Download ──────────────────────────────────────
            if await check_cancellation(session, job): return

            cached_video_ok = False
            if job.video_path:
                import os
                if os.path.exists(job.video_path):
                    size_mb = os.path.getsize(job.video_path) / (1024 * 1024)
                    # Validate: run ffprobe to confirm the file has a real video stream.
                    # Files < 1MB are almost certainly corrupt partial downloads.
                    if size_mb >= 1.0:
                        try:
                            probe_proc = await asyncio.create_subprocess_exec(
                                "ffprobe", "-v", "error",
                                "-select_streams", "v:0",
                                "-show_entries", "stream=codec_name",
                                "-of", "compact=p=0",
                                job.video_path,
                                stdout=asyncio.subprocess.PIPE,
                                stderr=asyncio.subprocess.PIPE,
                            )
                            probe_out, _ = await probe_proc.communicate()
                            cached_video_ok = bool(probe_out.decode().strip())
                        except Exception:
                            cached_video_ok = True  # ffprobe unavailable — trust the file
                    if not cached_video_ok:
                        await _update_job(session, job, status=JobStatus.DOWNLOADING, progress=5.0,
                            log_message=f"⚠️ Cached video invalid or too small ({size_mb:.1f}MB), re-downloading…",
                            video_path=None, audio_path=None, transcript=None,
                            translation=None, subtitle_path=None, output_path=None)
                        job.video_path = None

            if job.video_path and cached_video_ok:
                import os
                size_mb = os.path.getsize(job.video_path) / (1024 * 1024)
                await _update_job(session, job, status=JobStatus.DOWNLOADING, progress=20.0,
                    log_message=f"⏩ Skipping download (cached: {job.title}, {size_mb:.1f}MB)")
                dl_video_path = job.video_path
                dl_title = job.title or "Unknown Video"
            else:
                await _update_job(session, job, status=JobStatus.DOWNLOADING, progress=5.0,
                    log_message=f"🧩 [Hermes → tool] download_video(url=\"{job.url[:60]}...\")")
                await _update_job(session, job, progress=6.0,
                    log_message=f"🔽 [yt-dlp] Downloading from {job.url}...")
                
                try:
                    dl_result = await download_video(job.url, job.id)
                except Exception as ex:
                    raise ex

                dl_video_path = dl_result["video_path"]
                dl_title = dl_result["title"]
                import os
                size_mb = os.path.getsize(dl_video_path) / (1024*1024) if os.path.exists(dl_video_path) else 0
                await _update_job(
                    session, job, progress=20.0,
                    log_message=f"✅ Downloaded: \"{dl_title}\" | {dl_result.get('duration', '?')}s | {size_mb:.1f}MB | saved → {dl_video_path}",
                    video_path=dl_video_path, title=dl_title,
                    duration=dl_result["duration"], thumbnail_url=dl_result.get("thumbnail_url"),
                    platform=dl_result["platform"],
                )


            # ── Step 2: Transcribe ────────────────────────────────────
            if await check_cancellation(session, job): return
            if job.transcript and job.audio_path:
                seg_count = len(job.transcript.strip().split("\n"))
                await _update_job(session, job, status=JobStatus.TRANSCRIBING, progress=45.0,
                    log_message=f"⏩ Skipping transcription (cached: {seg_count} segments)")
                segments = [{"text": line.split("]", 1)[-1].strip() if "]" in line else line} 
                            for line in job.transcript.split("\n")]
            else:
                await _update_job(session, job, status=JobStatus.TRANSCRIBING, progress=24.0,
                    log_message=f"🧩 [Hermes → tool] transcribe_video(video_path, whisper_model=\"{settings.whisper_model}\")")
                await _update_job(session, job, progress=25.0,
                    log_message=f"🎙️ [Whisper:{settings.whisper_model}] Extracting audio & transcribing...")
                audio_path, segments_raw = await full_transcribe(dl_video_path, job.id)
                segments = segments_raw
                transcript_text = "\n".join(f"[{s['start']:.1f}-{s['end']:.1f}] {s['text']}" for s in segments)
                preview = segments[0]['text'][:80] if segments else '(empty)'
                await _update_job(session, job, progress=45.0,
                    log_message=f"✅ Transcribed: {len(segments)} segments | Model: {settings.whisper_model} | Preview: \"{preview}...\"",
                    audio_path=audio_path, transcript=transcript_text)

            # ── Step 3: Translate ─────────────────────────────────────
            if await check_cancellation(session, job): return
            if job.translation and job.subtitle_path:
                seg_count = len(job.translation.strip().split("\n"))
                await _update_job(session, job, status=JobStatus.TRANSLATING, progress=65.0,
                    log_message=f"⏩ Skipping translation (cached: {seg_count} segments)")
                translated = [{"text": line.split("]", 1)[-1].strip() if "]" in line else line} 
                              for line in job.translation.split("\n")]
            else:
                await _update_job(session, job, status=JobStatus.TRANSLATING, progress=49.0,
                    log_message=f"🧩 [Hermes → tool] translate_content(segments={len(segments)}, target=\"{job.target_language}\")")
                await _update_job(session, job, progress=50.0,
                    log_message=f"🌐 [Kimi K2.5 → {settings.kimi_base_url}] Translating {len(segments)} segments to {job.target_language}...")
                translated = await translate_segments(segments, job.target_language, job.id)
                translation_text = "\n".join(f"[{s.get('start', 0):.1f}-{s.get('end', 0):.1f}] {s['text']}" for s in translated)
                preview = translated[0]['text'][:80] if translated else '(empty)'
                await _update_job(session, job, progress=65.0,
                    log_message=f"✅ Translated: {len(translated)} segments | Preview: \"{preview}...\"",
                    translation=translation_text)

            # ── Step 3.5: Vision & Summary ────────────────────────────
            if await check_cancellation(session, job): return
            if job.frames_path and job.summary:
                await _update_job(session, job, progress=68.0,
                    log_message=f"⏩ Skipping vision (cached summary: {len(job.summary)} chars)")
            else:
                await _update_job(session, job, progress=65.5,
                    log_message=f"🧩 [Hermes → tool] analyze_content(extract_frames=5, summarize=True)")
                await _update_job(session, job, progress=66.0,
                    log_message=f"📸 [FFmpeg] Extracting keyframes from video for scene analysis...")
                try:
                    frames_dir = await extract_keyframes(dl_video_path, job.id, max_frames=5)
                    import os
                    frame_count = len([f for f in os.listdir(frames_dir) if f.endswith('.jpg')]) if os.path.exists(frames_dir) else 0
                    await _update_job(session, job, progress=67.0,
                        log_message=f"✅ Extracted {frame_count} keyframes → {frames_dir}", frames_path=frames_dir)
                    await _update_job(session, job, progress=68.0,
                        log_message=f"🧠 [Kimi K2.5 Vision] Sending {frame_count} images + transcript for multimodal summary...")
                    summary = await summarize_multimodal(frames_dir, transcript_text, job.id, target_language=job.target_language)
                    await _update_job(session, job, progress=69.0,
                        log_message=f"✅ AI Summary ({len(summary)} chars): \"{summary[:100]}...\"", summary=summary)
                except Exception as ve:
                    logger.warning(f"[Job {job.id}] Vision step failed: {ve}")
                    await _update_job(session, job, progress=69.0,
                        log_message=f"⚠️ Vision failed ({str(ve)[:120]}), using transcript as summary")
                    # Fallback: dùng transcript thay summary để luôn có data
                    fallback = transcript_text[:800].strip()
                    if fallback:
                        await _update_job(session, job, summary=fallback)

            # ── Step 4: Generate Subtitles ────────────────────────────
            if await check_cancellation(session, job): return
            if job.subtitle_path:
                srt_path = job.subtitle_path
                _derived_ass = srt_path.replace(".srt", ".ass")
                import os as _os
                if _os.path.exists(_derived_ass):
                    ass_path = _derived_ass
                    await _update_job(session, job, progress=75.0,
                        log_message=f"⏩ Skipping subtitles (cached: {srt_path})")
                else:
                    # .ass file missing (e.g. after server restart/retry) — regenerate from cached translated data
                    await _update_job(session, job, progress=69.5,
                        log_message=f"⚠️ Cached .ass missing, regenerating subtitles from cached SRT data...")
                    await _update_job(session, job, progress=70.0,
                        log_message=f"📝 [Subtitle Engine] Generating SRT + ASS dual-language subtitles...")
                    srt_path, ass_path = generate_dual_subtitles(translated, job.id)
                    await _update_job(session, job, progress=75.0,
                        log_message=f"✅ Subtitles regenerated: SRT → {srt_path} | ASS → {ass_path}",
                        subtitle_path=srt_path)
            else:
                await _update_job(session, job, progress=69.5,
                    log_message=f"🧩 [Hermes → tool] generate_subtitles(format=\"SRT+ASS\", dual_language=True)")
                await _update_job(session, job, progress=70.0,
                    log_message=f"📝 [Subtitle Engine] Generating SRT + ASS dual-language subtitles...")
                srt_path, ass_path = generate_dual_subtitles(translated, job.id)
                await _update_job(session, job, progress=75.0,
                    log_message=f"✅ Subtitles: SRT → {srt_path} | ASS → {ass_path}",
                    subtitle_path=srt_path)

            # ── Step 4.5: OCR Text Translation (Optional but triggered if enabled) ─────────
            ocr_filters = None
            if not job.output_path:
                await _update_job(session, job, progress=76.0,
                    log_message=f"🧩 [Hermes → tool] process_video_ocr(target=\"{job.target_language}\")")
                await _update_job(session, job, progress=76.5,
                    log_message=f"🕵️‍♂️ [EasyOCR + Kimi] Detecting and translating hardcoded text (this might take a while)...")
                    
                try:
                    from backend.services.ocr import process_video_ocr
                    
                    async def ocr_progress(prog: float, msg: str):
                        await _update_job(session, job, progress=76.5 + (prog * 0.1), log_message=f"  ↳ {msg}")
                        
                    ocr_filters = await process_video_ocr(dl_video_path, job.target_language, job.id, progress_callback=ocr_progress)
                except Exception as e:
                    logger.warning(f"[Job {job.id}] OCR translation failed: {e}")
                    await _update_job(session, job, progress=77.0,
                        log_message=f"⚠️ OCR text translation skipped: {str(e)[:200]}")

            # ── Step 5: Render Video ──────────────────────────────────
            if await check_cancellation(session, job): return
            if job.output_path:
                import os
                size_mb = os.path.getsize(job.output_path) / (1024*1024) if os.path.exists(job.output_path) else 0
                await _update_job(session, job, status=JobStatus.RENDERING, progress=90.0,
                    log_message=f"⏩ Skipping render (cached: {size_mb:.1f}MB)")
                output_path = job.output_path
            else:
                await _update_job(session, job, status=JobStatus.RENDERING, progress=77.0,
                    log_message=f"🧩 [Hermes → tool] render_with_subtitles(twitter_optimize={auto_publish})")
                await _update_job(session, job, progress=78.0,
                    log_message=f"🎬 [FFmpeg] Burning ASS subtitles into video (twitter_optimize={auto_publish})...")
                output_path = await render_video(dl_video_path, ass_path, job.id, optimize_for_twitter=auto_publish, ocr_filters=ocr_filters)
                import os
                size_mb = os.path.getsize(output_path) / (1024*1024) if os.path.exists(output_path) else 0
                await _update_job(session, job, progress=90.0,
                    log_message=f"✅ Rendered: {size_mb:.1f}MB → {output_path}",
                    output_path=output_path)

            # ── Step 6: Publish to X ──────────────────────────────────
            if await check_cancellation(session, job): return
            if auto_publish:
                await _update_job(
                    session, job,
                    status=JobStatus.PUBLISHING,
                    progress=91.5,
                    log_message="🧩 [Hermes → tool] publish_to_x(video=output.mp4, compose_tweet=True)",
                )
                await _update_job(
                    session, job,
                    progress=92.0,
                    log_message="🐦 [Playwright Chromium] Generating tweet text & launching headless browser...",
                )

                if job.tweet_text:
                    tweet_text = job.tweet_text
                    await _update_job(session, job, progress=93.0,
                        log_message=f"📝 Using cached tweet: \"{tweet_text[:60]}...\"")
                else:
                    await _update_job(session, job, progress=93.0,
                        log_message=f"📝 [Kimi K2.5] Generating engaging tweet caption...")
                    tweet_text = await generate_tweet_text(dl_title, translated, job.id, job.target_language)
                    await _update_job(session, job, progress=94.0,
                        log_message=f"✅ Tweet text: \"{tweet_text[:80]}...\"")

                x_account = await session.get(XAccount, job.x_account_id) if job.x_account_id else None
                x_cookies_json = x_account.cookies_json if x_account else None

                # Fallback: check BYOK user_keys_json for x_cookies_json
                if not x_cookies_json and job.user_keys_json:
                    try:
                        import json as _json
                        _user_keys = _json.loads(job.user_keys_json)
                        x_cookies_json = _user_keys.get("x_cookies_json")
                        if x_cookies_json:
                            logger.info(f"[Job {job.id}] Using BYOK x_cookies_json from user_keys")
                    except Exception:
                        pass

                # Last fallback: first account in DB
                if not x_cookies_json:
                    from sqlalchemy import select as _select
                    first_acc = (await session.execute(_select(XAccount).limit(1))).scalars().first()
                    if first_acc and first_acc.cookies_json:
                        x_cookies_json = first_acc.cookies_json
                        x_account = first_acc
                        logger.info(f"[Job {job.id}] Falling back to first DB account: @{first_acc.username}")

                account_label = f"@{x_account.username}" if x_account and x_account.username else "X account"

                await _update_job(session, job, progress=95.0,
                    log_message=f"🚀 [Playwright] Publishing via {account_label} → x.com/compose/tweet...")

                pub_result = await publish_to_x(output_path, tweet_text, job.id, x_cookies_json)

                await _update_job(
                    session, job,
                    progress=99.0,
                    log_message=f"🎉 Published! Tweet ID: {pub_result['tweet_id']} | URL: {pub_result['tweet_url']}",
                    tweet_id=pub_result["tweet_id"],
                    tweet_text=tweet_text,
                )
                await _update_job(
                    session, job,
                    progress=100.0,
                    status=JobStatus.COMPLETED,
                    log_message=f"🤖 [Hermes Agent] All tools executed successfully · pipeline finished · handing control back to user",
                    completed_at=datetime.now(timezone.utc),
                )
            else:
                await _update_job(
                    session, job,
                    progress=99.0,
                    log_message="✅ Pipeline complete (auto-publish OFF, video ready for manual download)",
                )
                await _update_job(
                    session, job,
                    progress=100.0,
                    status=JobStatus.COMPLETED,
                    log_message=f"🤖 [Hermes Agent] All tools executed successfully · pipeline finished · handing control back to user",
                    completed_at=datetime.now(timezone.utc),
                )

        except Exception as e:
            import traceback
            tb = traceback.format_exc()
            logger.exception(f"[Job {job_id}] Pipeline failed")
            await _update_job(
                session, job,
                status=JobStatus.FAILED,
                log_message=f"❌ [Hermes Agent] Tool failed at stage \"{job.status}\" → {repr(e)}\n\n{tb[:500]}",
                error_message=tb,
            )
        finally:
            # Cleanup from cancelled set
            if job_id in _cancelled_jobs:
                _cancelled_jobs.remove(job_id)

async def run_script_task(job_id: int):
    """
    Execute a shortened pipeline specifically for Script Extraction.
    Steps:
    1. Download video
    2. Transcribe audio
    3. Rewrite script with Kimi K2.6
    """
    factory = get_session_factory()
    
    async with factory() as session:
        job = await session.get(Job, job_id)
        if not job:
            return

        settings = get_job_settings(job.user_keys_json)

        try:
            # ── Step 1: Download Video ────────────────────────────────
            await _update_job(session, job, status=JobStatus.DOWNLOADING, progress=5.0,
                log_message=f"🧩 [Hermes → tool] download_video(url=\"{job.url[:60]}...\")")
            await _update_job(session, job, progress=6.0,
                log_message=f"🔽 [yt-dlp] Downloading from {job.url}...")
            
            dl_result = await download_video(job.url, job.id)
            dl_video_path = dl_result["video_path"]
            dl_title = dl_result["title"]
            duration = dl_result.get("duration")

            import os
            size_mb = os.path.getsize(dl_video_path) / (1024*1024) if os.path.exists(dl_video_path) else 0
            await _update_job(session, job, progress=25.0,
                log_message=f"✅ Downloaded: \"{dl_title}\" | {duration or '?'}s | {size_mb:.1f}MB",
                title=dl_title, duration=duration, video_path=dl_video_path)

            # ── Step 2: Transcribe Video ──────────────────────────────
            await _update_job(session, job, status=JobStatus.TRANSCRIBING, progress=30.0,
                log_message=f"🧩 [Hermes → tool] transcribe_video(whisper_model=\"{settings.whisper_model}\")")
            await _update_job(session, job, progress=31.0,
                log_message=f"🎙️ [Whisper:{settings.whisper_model}] Extracting audio & transcribing...")
            
            audio_path, transcript_segments = await full_transcribe(dl_video_path, job.id)
            transcript_text = " ".join([s["text"] for s in transcript_segments])
            preview = transcript_segments[0]['text'][:80] if transcript_segments else '(empty)'
            
            await _update_job(session, job, progress=50.0,
                log_message=f"✅ Transcribed: {len(transcript_segments)} segments | Preview: \"{preview}...\"",
                audio_path=audio_path, transcript=transcript_text)
                
            # ── Step 2.5: Vision & Summary ────────────────────────────
            await _update_job(session, job, progress=52.0,
                log_message=f"🧩 [Hermes → tool] analyze_content(extract_frames=5, summarize=True)")
            await _update_job(session, job, progress=53.0,
                log_message=f"📸 [FFmpeg] Extracting keyframes from video for scene analysis...")
            try:
                frames_dir = await extract_keyframes(dl_video_path, job.id, max_frames=5)
                import os
                frame_count = len([f for f in os.listdir(frames_dir) if f.endswith('.jpg')]) if os.path.exists(frames_dir) else 0
                await _update_job(session, job, progress=54.0,
                    log_message=f"✅ Extracted {frame_count} keyframes → {frames_dir}", frames_path=frames_dir)
                
                # Map script_xx prefix to actual language names
                lang_code = job.target_language.replace("script_", "") if job.target_language.startswith("script_") else "vi"
                language_map = {"vi": "Vietnamese", "en": "English", "zh": "Chinese", "ja": "Japanese", "ko": "Korean"}
                target_lang = language_map.get(lang_code, "Vietnamese")

                await _update_job(session, job, progress=55.0,
                    log_message=f"🧠 [Kimi K2.5 Vision] Sending {frame_count} images + transcript for multimodal summary...")
                summary = await summarize_multimodal(frames_dir, transcript_text, job.id, target_language=target_lang)
                await _update_job(session, job, progress=56.0,
                    log_message=f"✅ AI Summary ({len(summary)} chars): \"{summary[:100]}...\"", summary=summary)
            except Exception as ve:
                logger.warning(f"[Job {job.id}] Vision step failed: {ve}")
                await _update_job(session, job, progress=56.0,
                    log_message=f"⚠️ Vision step skipped: {str(ve)[:200]}")
                summary = transcript_text[:1000]

            # ── Step 3: Rewrite Script with Kimi ──────────────────────
            await _update_job(session, job, status=JobStatus.TRANSLATING, progress=58.0,
                log_message=f"🧩 [Hermes → tool] rewrite_script(scenes=5, style=\"cinematic\")")
                
            from backend.agent.tools import execute_tool
            import json
            
            await _update_job(session, job, progress=60.0,
                log_message=f"📝 [Kimi K2.6] Analyzing content and rewriting script to {target_lang}...")
                
            script_result = await execute_tool("rewrite_script", {
                "summary": summary,
                "transcript": transcript_text,
                "num_scenes": 5,
                "style": "cinematic",
                "target_language": target_lang
            })
            
            await _update_job(session, job, progress=90.0,
                log_message=f"✅ Script generated: {len(script_result['scenes'])} scenes",
                script_json=json.dumps(script_result["scenes"], ensure_ascii=False))
            
            await session.refresh(job)
            
            await _update_job(
                session, job,
                progress=100.0,
                status=JobStatus.COMPLETED,
                log_message=f"🎉 [Hermes Agent] Script extraction complete — \"{dl_title}\"",
                completed_at=datetime.now(timezone.utc),
            )
        except Exception as e:
            logger.exception(f"[Job {job_id}] Script extraction failed")
            await _update_job(
                session, job,
                status=JobStatus.FAILED,
                log_message=f"❌ Pipeline failed: {str(e)[:500]}",
                error_message=str(e),
            )

