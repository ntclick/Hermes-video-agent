"""
API Routes — Autonomous Content Bridge
CRUD endpoints for managing video processing jobs.
"""
import asyncio
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, HttpUrl
from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import get_db
from backend.models import Job, JobStatus, Platform
from backend.services.downloader import detect_platform
from backend.workers.pipeline import run_pipeline, run_script_task, cancel_job_pipeline

logger = logging.getLogger("content-bridge.api")

router = APIRouter(prefix="/api/jobs", tags=["jobs"])


# ── Request/Response schemas ──────────────────────────────────

class JobCreate(BaseModel):
    url: str
    target_language: str = "vi"
    auto_publish: bool = True
    x_account_id: int | None = None


class JobResponse(BaseModel):
    id: int
    url: str
    platform: str | None
    status: str
    progress: float
    title: str | None
    duration: float | None
    thumbnail_url: str | None
    target_language: str
    tweet_id: str | None
    tweet_text: str | None
    logs: str | None
    error_message: str | None
    created_at: str | None
    updated_at: str | None
    completed_at: str | None


# ── Endpoints ─────────────────────────────────────────────────

@router.post("", response_model=JobResponse, status_code=201)
async def create_job(
    body: JobCreate,
    request: Request,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    """Create a new video processing job."""
    platform = detect_platform(body.url)

    # Extract user-provided API keys from request headers (BYOK)
    import json
    user_keys = {}
    header_map = {
        "x-kimi-key": "kimi_api_key",
        "x-hermes-key": "hermes_api_key",
        "x-fal-key": "fal_api_key",
        "x-hermes-provider": "hermes_provider",
        "x-hermes-model": "hermes_model",
        "x-douyin-cookies": "douyin_cookies",
        "x-x-cookies": "x_cookies_json",
    }
    from urllib.parse import unquote
    for header, key_name in header_map.items():
        val = request.headers.get(header)
        if val:
            user_keys[key_name] = unquote(val)

    job = Job(
        url=body.url,
        platform=platform,
        target_language=body.target_language,
        x_account_id=body.x_account_id,
        status=JobStatus.PENDING,
        progress=0.0,
        user_keys_json=json.dumps(user_keys) if user_keys else None,
    )
    job.append_log(f"📋 Job created for {platform.value}: {body.url}")
    if user_keys:
        job.append_log(f"🔑 Using user-provided keys: {', '.join(user_keys.keys())}")

    db.add(job)
    await db.commit()
    await db.refresh(job)

    logger.info(f"Created job {job.id}: {body.url} (BYOK keys: {list(user_keys.keys()) if user_keys else 'none'})")

    # Launch pipeline in background
    if body.target_language.startswith("script_") or body.target_language == "script":
        background_tasks.add_task(run_script_task, job.id)
    else:
        background_tasks.add_task(run_pipeline, job.id, body.auto_publish)

    return JobResponse(**job.to_dict())


@router.get("", response_model=list[JobResponse])
async def list_jobs(
    limit: int = 20,
    offset: int = 0,
    status: str | None = None,
    db: AsyncSession = Depends(get_db),
):
    """List all jobs, newest first."""
    query = select(Job).order_by(desc(Job.created_at)).offset(offset).limit(limit)

    if status:
        try:
            status_enum = JobStatus(status)
            query = query.where(Job.status == status_enum)
        except ValueError:
            pass

    result = await db.execute(query)
    jobs = result.scalars().all()
    return [JobResponse(**j.to_dict()) for j in jobs]


@router.get("/{job_id}", response_model=JobResponse)
async def get_job(job_id: int, db: AsyncSession = Depends(get_db)):
    """Get a specific job by ID."""
    job = await db.get(Job, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return JobResponse(**job.to_dict())


@router.delete("/{job_id}")
async def delete_job(job_id: int, db: AsyncSession = Depends(get_db)):
    """Delete a job and its associated files."""
    job = await db.get(Job, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    # Delete files from disk
    import shutil
    from backend.config import get_settings
    settings = get_settings()
    job_dir = settings.downloads_dir / str(job.id)
    if job_dir.exists():
        shutil.rmtree(job_dir, ignore_errors=True)

    await db.delete(job)
    await db.commit()
    return {"message": f"Job {job_id} deleted"}


@router.post("/{job_id}/cancel")
async def cancel_job(
    job_id: int,
    db: AsyncSession = Depends(get_db),
):
    """Cancel a running job."""
    job = await db.get(Job, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    if job.status in (JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED):
        raise HTTPException(
            status_code=400,
            detail=f"Cannot cancel job in state: {job.status}",
        )

    # Signal the pipeline to stop
    cancel_job_pipeline(job_id)
    
    # Update status in DB immediately
    job.status = JobStatus.CANCELLED
    job.append_log("⏹ Job cancellation requested by user.")
    
    db.add(job)
    await db.commit()
    return {"message": f"Cancellation requested for job {job_id}"}


@router.post("/{job_id}/retry", response_model=JobResponse)
async def retry_job(
    job_id: int,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    """Retry a failed job."""
    job = await db.get(Job, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    if job.status not in (JobStatus.FAILED, JobStatus.CANCELLED):
        raise HTTPException(
            status_code=400,
            detail=f"Can only retry failed/cancelled jobs (current: {job.status})",
        )

    # Calculate progress based on existing artifacts
    if job.output_path:
        job.progress = 90.0
    elif job.subtitle_path:
        job.progress = 75.0
    elif job.translation:
        job.progress = 65.0
    elif job.transcript:
        job.progress = 45.0
    elif job.video_path:
        job.progress = 20.0
    else:
        job.progress = 0.0

    job.status = JobStatus.PENDING
    job.error_message = None
    job.append_log("🔄 Retrying job from last successful step...")

    db.add(job)
    await db.commit()
    await db.refresh(job)

    # Auto-publish on retry if job has an X account assigned
    should_publish = job.x_account_id is not None
    background_tasks.add_task(run_pipeline, job.id, should_publish)


    return JobResponse(**job.to_dict())


@router.get("/stats/summary")
async def get_stats(db: AsyncSession = Depends(get_db)):
    """Get job statistics summary."""
    result = await db.execute(select(Job))
    jobs = result.scalars().all()

    stats = {
        "total": len(jobs),
        "pending": sum(1 for j in jobs if j.status == JobStatus.PENDING),
        "processing": sum(
            1
            for j in jobs
            if j.status
            in (
                JobStatus.DOWNLOADING,
                JobStatus.TRANSCRIBING,
                JobStatus.TRANSLATING,
                JobStatus.RENDERING,
                JobStatus.PUBLISHING,
            )
        ),
        "completed": sum(1 for j in jobs if j.status == JobStatus.COMPLETED),
        "failed": sum(1 for j in jobs if j.status == JobStatus.FAILED),
    }
    return stats


# ── Update Job Fields ────────────────────────────────────────
class JobUpdate(BaseModel):
    tweet_text: str | None = None
    script_json: str | None = None


@router.patch("/{job_id}", response_model=JobResponse)
async def update_job_fields(
    job_id: int,
    body: JobUpdate,
    db: AsyncSession = Depends(get_db),
):
    """Update editable job fields (tweet_text, script_json)."""
    job = await db.get(Job, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    updated = []
    if body.tweet_text is not None:
        job.tweet_text = body.tweet_text
        updated.append("tweet_text")
    if body.script_json is not None:
        job.script_json = body.script_json
        updated.append("script_json")

    if updated:
        job.append_log(f"✏️ Updated: {', '.join(updated)}")
        db.add(job)
        await db.commit()
        await db.refresh(job)

    return JobResponse(**job.to_dict())


# ── Manual Publish to X ──────────────────────────────────────
@router.post("/{job_id}/publish")
async def publish_job_to_x(
    job_id: int,
    db: AsyncSession = Depends(get_db),
):
    """Manually publish a completed job to X/Twitter."""
    job = await db.get(Job, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if not job.output_path:
        raise HTTPException(status_code=400, detail="No rendered video. Complete pipeline first.")

    from backend.models import XAccount
    x_account = await db.get(XAccount, job.x_account_id) if job.x_account_id else None
    if not x_account or not x_account.cookies_json:
        raise HTTPException(status_code=400, detail="No X account assigned or cookies missing.")

    import asyncio
    asyncio.create_task(_run_publish(job_id))
    return {"message": "Publishing to X started", "job_id": job_id}


async def _run_publish(job_id: int):
    """Background task: generate tweet text from summary + publish to X."""
    from backend.database import async_session_factory
    from backend.services.publisher import publish_to_x
    from backend.models import XAccount
    from backend.config import get_settings

    async with async_session_factory() as session:
        job = await session.get(Job, job_id)
        if not job:
            return

        try:
            # Generate tweet text using Kimi from summary
            if not job.tweet_text:
                job.append_log("📝 [Kimi K2.6] Generating tweet from summary...")
                session.add(job)
                await session.commit()

                settings = get_settings()
                from openai import AsyncOpenAI
                client = AsyncOpenAI(api_key=settings.kimi_api_key, base_url=settings.kimi_base_url)

                _lang = {"vi": "Vietnamese", "en": "English", "zh": "Chinese", "ja": "Japanese", "ko": "Korean"}
                lang_name = _lang.get(job.target_language[:2], job.target_language)

                response = await client.chat.completions.create(
                    model="kimi-k2.6",
                    messages=[
                        {"role": "system", "content": (
                            f"Generate a short engaging tweet in {lang_name} for a translated video. "
                            f"Include emojis and hashtags. Under 250 chars. No quotes."
                        )},
                        {"role": "user", "content": f"Title: {job.title}\nSummary: {(job.summary or '')[:500]}"},
                    ],
                    extra_body={"thinking": {"type": "disabled"}},
                    max_tokens=200,
                )
                tweet_text = response.choices[0].message.content.strip().strip('"')
                job.tweet_text = tweet_text
                job.append_log(f'✅ Tweet: "{tweet_text[:80]}..."')
            else:
                tweet_text = job.tweet_text
                job.append_log(f'📝 Using existing tweet: "{tweet_text[:60]}..."')

            # Publish via Playwright
            x_account = await session.get(XAccount, job.x_account_id)
            x_cookies = x_account.cookies_json if x_account else None
            label = f"@{x_account.username}" if x_account and x_account.username else "default"

            job.append_log(f"🚀 [Playwright] Publishing via {label} → x.com...")
            job.status = JobStatus.PUBLISHING
            session.add(job)
            await session.commit()

            pub_result = await publish_to_x(job.output_path, tweet_text, job.id, x_cookies)

            job.tweet_id = pub_result.get("tweet_id")
            job.status = JobStatus.COMPLETED
            job.append_log(f"🎉 Published! Tweet ID: {job.tweet_id}")
            session.add(job)
            await session.commit()

        except Exception as e:
            job.status = JobStatus.COMPLETED
            job.append_log(f"❌ Publish failed: {str(e)[:200]}")
            session.add(job)
            await session.commit()


# ── Serve Raw Video ──────────────────────────────────────────
@router.get("/{job_id}/raw-video")
async def get_raw_video(job_id: int, db: AsyncSession = Depends(get_db)):
    """Serve the raw downloaded video for the job."""
    job = await db.get(Job, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if not job.video_path:
        raise HTTPException(status_code=404, detail="Raw video not available")
    
    import os
    if not os.path.exists(job.video_path):
        raise HTTPException(status_code=404, detail="Video file not found on disk")
        
    return FileResponse(job.video_path, media_type="video/mp4")


# ── Regenerate Cover (re-compose from existing scenes) ───────
@router.post("/{job_id}/regenerate-cover")
async def regenerate_cover(job_id: int, db: AsyncSession = Depends(get_db)):
    """Re-compose cover video from existing AI scene images."""
    job = await db.get(Job, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if not job.ai_scenes_path:
        raise HTTPException(status_code=400, detail="No AI scenes found. Generate cover first.")
    if not job.audio_path:
        raise HTTPException(status_code=400, detail="No audio file. Run transcription first.")

    import asyncio
    asyncio.create_task(_run_recompose(job_id))
    return {"message": "Cover re-composition started", "job_id": job_id}


async def _run_recompose(job_id: int):
    """Background: Re-compose cover video from existing scene images."""
    import logging
    from datetime import datetime, timezone
    from backend.database import async_session
    from backend.services.cover_composer import compose_cover_video

    logger = logging.getLogger("content-bridge.cover")

    async with async_session() as session:
        job = await session.get(Job, job_id)
        if not job:
            return

        ws_manager = None
        try:
            from backend.main import ws_manager as _ws
            ws_manager = _ws
        except Exception:
            pass

        async def _log(msg: str, **kwargs):
            ts = datetime.now(timezone.utc).strftime("%H:%M:%S")
            entry = f"[{ts}] {msg}"
            job.logs = (job.logs + f"\n{entry}") if job.logs else entry
            for k, v in kwargs.items():
                if hasattr(job, k):
                    setattr(job, k, v)
            job.updated_at = datetime.now(timezone.utc)
            await session.commit()
            if ws_manager:
                try:
                    await ws_manager.broadcast({"type": "job_update", "job": job.to_dict()})
                except Exception:
                    pass

        try:
            import os
            await _log("🔄 Re-composing cover video from existing scenes...")

            subtitle_path = job.subtitle_path.replace(".srt", ".ass") if job.subtitle_path else None
            cover_path = await compose_cover_video(
                scenes_dir=job.ai_scenes_path,
                audio_path=job.audio_path,
                subtitle_path=subtitle_path,
                job_id=job_id,
            )

            size_mb = os.path.getsize(cover_path) / (1024 * 1024) if os.path.exists(cover_path) else 0
            await _log(f"🎉 Cover video re-composed! {size_mb:.1f}MB → {cover_path}", cover_path=cover_path)
        except Exception as e:
            logger.exception(f"[Job {job_id}] Cover re-composition failed")
            await _log(f"❌ Cover re-composition failed: {str(e)[:500]}")


# ── Rewrite Script & Regenerate Cover ────────────────────────
@router.post("/{job_id}/rewrite-script")
async def rewrite_script_and_regenerate(job_id: int, db: AsyncSession = Depends(get_db)):
    """AI rewrites the cover script, generates new images, and composes a new cover video."""
    job = await db.get(Job, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if not job.summary or not job.transcript:
        raise HTTPException(status_code=400, detail="Need summary + transcript. Run main pipeline first.")
    if not job.audio_path:
        raise HTTPException(status_code=400, detail="No audio file. Run transcription first.")

    import asyncio
    asyncio.create_task(_run_cover_pipeline(job_id))
    return {"message": "Script rewrite + cover regeneration started", "job_id": job_id}


# ── Generate Cover Video ─────────────────────────────────────
@router.post("/{job_id}/generate-cover")
async def generate_cover(job_id: int, db: AsyncSession = Depends(get_db)):
    """Trigger AI cover video generation for an existing completed/failed job."""
    job = await db.get(Job, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    if not job.summary or not job.transcript:
        raise HTTPException(
            status_code=400,
            detail="Job needs summary and transcript first. Run the main pipeline first.",
        )
    if not job.audio_path:
        raise HTTPException(status_code=400, detail="Job has no audio file. Run transcription first.")

    # Launch cover pipeline in background
    import asyncio
    asyncio.create_task(_run_cover_pipeline(job_id))

    return {"message": "Cover generation started", "job_id": job_id}


async def _run_cover_pipeline(job_id: int):
    """Background task: Hermes Agent generates cover video."""
    import json
    import logging
    from datetime import datetime, timezone
    from backend.database import async_session
    from backend.config import get_settings
    from backend.services.fal_generator import generate_all_scenes
    from backend.services.cover_composer import compose_cover_video

    logger = logging.getLogger("content-bridge.cover")

    async with async_session() as session:
        job = await session.get(Job, job_id)
        if not job:
            return

        ws_manager = None
        try:
            from backend.main import ws_manager as _ws
            ws_manager = _ws
        except Exception:
            pass

        async def _log(msg: str, **kwargs):
            """Helper to log + update job + broadcast."""
            ts = datetime.now(timezone.utc).strftime("%H:%M:%S")
            entry = f"[{ts}] {msg}"
            if job.logs:
                job.logs += f"\n{entry}"
            else:
                job.logs = entry
            for k, v in kwargs.items():
                if hasattr(job, k):
                    setattr(job, k, v)
            job.updated_at = datetime.now(timezone.utc)
            await session.commit()
            if ws_manager:
                try:
                    await ws_manager.broadcast({"type": "job_update", "job": job.to_dict()})
                except Exception:
                    pass

        try:
            settings = get_settings()

            # Step 1: Hermes rewrites the script
            await _log("📜 [Hermes Agent] Analyzing video content and writing creative script...")

            from openai import AsyncOpenAI
            client = AsyncOpenAI(
                api_key=settings.hermes_api_key,
                base_url=settings.hermes_base_url,
            )

            prompt = f"""Based on this video, create a cinematic visual script with exactly 5 scenes.

VIDEO SUMMARY:
{job.summary[:1000]}

TRANSCRIPT:
{job.transcript[:2000]}

Return a JSON array of scenes. Each scene must have:
- "scene": scene number (1-5)
- "narration": what happens in this scene (1-2 sentences)  
- "image_prompt": detailed prompt for AI image generation. Be very specific about: subjects, composition, lighting, color palette, camera angle, mood. Do NOT include any text/words in the image.
- "duration": seconds (3-8)

Return ONLY the JSON array."""

            response = await client.chat.completions.create(
                model=settings.hermes_model,
                messages=[
                    {"role": "system", "content": "You are a creative director. Generate scene breakdowns for AI image generation."},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.7,
                max_tokens=2000,
            )

            raw = response.choices[0].message.content.strip()
            if "```json" in raw:
                raw = raw.split("```json")[1].split("```")[0].strip()
            elif "```" in raw:
                raw = raw.split("```")[1].split("```")[0].strip()

            import re
            try:
                scenes = json.loads(raw)
            except json.JSONDecodeError:
                match = re.search(r'\[.*\]', raw, re.DOTALL)
                if match:
                    scenes = json.loads(match.group())
                else:
                    raise ValueError(f"Hermes returned invalid JSON: {raw[:200]}")

            script_json = json.dumps(scenes, ensure_ascii=False, indent=2)
            await _log(
                f"✅ [Hermes] Script generated: {len(scenes)} scenes | Model: {settings.hermes_model}",
                script_json=script_json,
            )

            # Log each scene
            for s in scenes:
                await _log(f"  🎬 Scene {s.get('scene', '?')}: {s.get('narration', '')[:80]}...")

            # Step 2: Generate AI images
            await _log(f"🎨 [fal.ai FLUX] Generating {len(scenes)} scene images...")
            
            scenes_dir = await generate_all_scenes(scenes, job_id, style="cinematic")
            
            import os
            img_count = len([f for f in os.listdir(scenes_dir) if f.endswith('.jpg')]) if os.path.exists(scenes_dir) else 0
            await _log(
                f"✅ [fal.ai] Generated {img_count} AI images → {scenes_dir}",
                ai_scenes_path=scenes_dir,
            )

            # Step 3: Compose cover video
            subtitle_path = job.subtitle_path.replace(".srt", ".ass") if job.subtitle_path else None
            await _log(f"🎬 [FFmpeg] Composing cover video with Ken Burns effects...")

            cover_path = await compose_cover_video(
                scenes_dir=scenes_dir,
                audio_path=job.audio_path,
                subtitle_path=subtitle_path,
                job_id=job_id,
            )

            size_mb = os.path.getsize(cover_path) / (1024 * 1024) if os.path.exists(cover_path) else 0
            await _log(
                f"🎉 Cover video complete! {size_mb:.1f}MB → {cover_path}",
                cover_path=cover_path,
            )

        except Exception as e:
            logger.exception(f"[Job {job_id}] Cover generation failed")
            await _log(f"❌ Cover generation failed: {str(e)[:500]}")

@router.post("/{job_id}/custom-script")
async def write_custom_script(job_id: int, background_tasks: BackgroundTasks, db: AsyncSession = Depends(get_db)):
    """Generate a custom video script based on the translated transcript."""
    job = await db.get(Job, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    if not job.transcript:
        raise HTTPException(status_code=400, detail="Job has no transcript. Run pipeline first.")

    # Background task to write script
    async def _generate_script():
        from backend.database import get_session_factory
        from backend.workers.pipeline import _broadcast_update
        from openai import AsyncOpenAI
        
        factory = get_session_factory()
        async with factory() as session:
            j = await session.get(Job, job_id)
            
            async def _log(msg: str, **kwargs):
                j.append_log(msg)
                for k, v in kwargs.items():
                    setattr(j, k, v)
                session.add(j)
                await session.commit()
                await _broadcast_update(job_id, {"type": "job_update", "job": j.to_dict()})
            
            await _log(f"✍️ [Hermes] Writing custom TikTok/Reels script based on transcript...")
            
            settings = get_settings()
            if settings.hermes_provider == "kimi":
                api_key = settings.kimi_api_key
                base_url = settings.kimi_base_url
            else:
                api_key = settings.hermes_api_key
                base_url = settings.hermes_base_url

            client = AsyncOpenAI(api_key=api_key, base_url=base_url)
            
            prompt = (
                "You are an expert viral video scriptwriter for TikTok and YouTube Shorts.\n"
                "Read the following translated transcript of a video and write a highly engaging, punchy script "
                "that summarizes the best parts. Format the script as a list of scenes with narration and visual cues.\n\n"
                f"Transcript:\n{j.translation or j.transcript}\n\n"
                "Return ONLY a JSON array of objects with keys: 'scene', 'narration', 'visual_cue', 'duration'."
            )

            try:
                response = await client.chat.completions.create(
                    model=settings.hermes_model,
                    messages=[{"role": "user", "content": prompt}],
                    max_tokens=2000,
                )
                
                raw = response.choices[0].message.content.strip()
                if "```json" in raw:
                    raw = raw.split("```json")[1].split("```")[0].strip()
                elif "```" in raw:
                    raw = raw.split("```")[1].split("```")[0].strip()

                import json, re
                try:
                    scenes = json.loads(raw)
                except json.JSONDecodeError:
                    match = re.search(r'\[.*\]', raw, re.DOTALL)
                    if match:
                        scenes = json.loads(match.group())
                    else:
                        raise ValueError(f"Invalid JSON returned: {raw[:100]}")

                # Save the script into the same script_json field to reuse the UI component
                # Map visual_cue to image_prompt so the UI renders it
                for s in scenes:
                    if 'visual_cue' in s:
                        s['image_prompt'] = s['visual_cue']
                
                script_json = json.dumps(scenes, ensure_ascii=False, indent=2)
                await _log(f"✅ Script writing complete ({len(scenes)} scenes)!", script_json=script_json)
                
            except Exception as e:
                logger.exception("Failed to write custom script")
                await _log(f"❌ Script writing failed: {str(e)[:500]}")

    background_tasks.add_task(_generate_script)
    return {"message": "Writing script in background"}
