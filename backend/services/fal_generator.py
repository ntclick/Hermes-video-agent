"""
fal.ai Image Generator — Autonomous Content Bridge
Uses fal.ai FLUX model to generate AI scene images from text prompts.
"""
import asyncio
import logging
import os
import httpx
from pathlib import Path

from backend.config import get_settings

logger = logging.getLogger("content-bridge.fal_generator")


async def generate_scene_image(prompt: str, job_id: int, scene_num: int, style: str = "cinematic") -> str:
    """
    Generate a single scene image using fal.ai FLUX schnell.
    
    Args:
        prompt: Scene description prompt
        job_id: Job identifier
        scene_num: Scene number (1-based)
        style: Image style (cinematic, anime, photorealistic)
        
    Returns:
        Local file path of the downloaded image
    """
    settings = get_settings()
    if not settings.fal_api_key:
        raise ValueError("FAL_API_KEY not configured. Add it in Settings.")

    scenes_dir = Path(settings.data_dir) / "processed" / str(job_id) / "ai_scenes"
    scenes_dir.mkdir(parents=True, exist_ok=True)
    output_path = scenes_dir / f"scene_{scene_num:02d}.jpg"

    # Style-aware prompt enhancement
    style_suffixes = {
        "cinematic": ", cinematic lighting, 8k, dramatic composition, film still, professional photography",
        "anime": ", anime style, Studio Ghibli quality, vibrant colors, detailed illustration",
        "photorealistic": ", photorealistic, ultra-detailed, 8k resolution, professional DSLR photo",
        "documentary": ", documentary photography, real-world, natural lighting, editorial photo",
    }
    enhanced_prompt = prompt + style_suffixes.get(style, style_suffixes["cinematic"])

    logger.info(f"[Job {job_id}] Generating scene {scene_num} with fal.ai FLUX: \"{prompt[:80]}...\"")

    try:
        import fal_client
        # Set the API key
        os.environ["FAL_KEY"] = settings.fal_api_key

        # Use fal_client async subscribe
        result = await asyncio.to_thread(
            fal_client.subscribe,
            "fal-ai/flux/schnell",
            arguments={
                "prompt": enhanced_prompt,
                "image_size": "landscape_16_9",
                "num_inference_steps": 4,
                "num_images": 1,
            },
        )

        image_url = result["images"][0]["url"]
        logger.info(f"[Job {job_id}] Scene {scene_num} generated. Downloading from {image_url[:60]}...")

        # Download the image
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(image_url)
            resp.raise_for_status()
            output_path.write_bytes(resp.content)

        logger.info(f"[Job {job_id}] Scene {scene_num} saved → {output_path}")
        return str(output_path)

    except Exception as e:
        logger.error(f"[Job {job_id}] fal.ai generation failed for scene {scene_num}: {e}")
        raise


async def generate_all_scenes(scenes: list[dict], job_id: int, style: str = "cinematic") -> str:
    """
    Generate images for all scenes using fal.ai.
    
    Args:
        scenes: List of dicts with 'scene', 'image_prompt' keys
        job_id: Job identifier
        style: Image style
    
    Returns:
        Path to directory containing all generated images
    """
    settings = get_settings()
    scenes_dir = Path(settings.data_dir) / "processed" / str(job_id) / "ai_scenes"
    scenes_dir.mkdir(parents=True, exist_ok=True)

    logger.info(f"[Job {job_id}] Generating {len(scenes)} scene images with fal.ai FLUX ({style})...")

    for scene in scenes:
        scene_num = scene.get("scene", 1)
        prompt = scene.get("image_prompt", scene.get("narration", ""))
        if not prompt:
            continue
        await generate_scene_image(prompt, job_id, scene_num, style)
        # Small delay between calls to be respectful to API
        await asyncio.sleep(0.5)

    logger.info(f"[Job {job_id}] All {len(scenes)} scene images generated → {scenes_dir}")
    return str(scenes_dir)
