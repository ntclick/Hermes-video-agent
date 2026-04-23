"""
Translator Service — Autonomous Content Bridge
Uses Kimi K2.5 API (Moonshot AI) to translate transcripts to Vietnamese.
"""
import json
import logging
from openai import AsyncOpenAI

from backend.config import get_settings

logger = logging.getLogger("content-bridge.translator")

# Maximum segments per API call to avoid token limits
BATCH_SIZE = 20


def _get_kimi_client() -> AsyncOpenAI:
    """Create Kimi API client (OpenAI-compatible)."""
    settings = get_settings()
    return AsyncOpenAI(
        api_key=settings.kimi_api_key,
        base_url=settings.kimi_base_url,
    )


async def translate_segments(
    segments: list[dict],
    target_language: str = "vi",
    job_id: int = 0,
) -> list[dict]:
    """
    Translate transcript segments using Kimi K2.5.

    Args:
        segments: list of {"start": float, "end": float, "text": str}
        target_language: ISO 639-1 code (default: "vi" for Vietnamese)
        job_id: for logging

    Returns:
        Same structure with translated text
    """
    if not segments:
        return []

    client = _get_kimi_client()
    
    # Process in batches concurrently to speed up translation
    import asyncio
    # Moonshot limits concurrency to 3, so we use 2 to be safe
    sem = asyncio.Semaphore(2)
    
    async def _translate_batch(batch, batch_num, total_batches):
        async with sem:
            logger.info(f"[Job {job_id}] Translating batch {batch_num}/{total_batches}")

            segments_text = json.dumps(
                [{"id": idx, "text": s["text"]} for idx, s in enumerate(batch)],
                ensure_ascii=False,
            )

            lang_names = {
                "vi": "Vietnamese",
                "en": "English",
                "zh": "Chinese",
                "ja": "Japanese",
                "ko": "Korean",
            }
            lang_name = lang_names.get(target_language, target_language)

            system_prompt = f"""You are a professional subtitle translator. You MUST translate the following subtitle segments into {lang_name}.

CRITICAL RULES:
1. You MUST translate the text into {lang_name}. DO NOT return the original Chinese text.
2. Return ONLY a valid JSON array with the exact same structure: [{{"start": 0.0, "end": 1.0, "text": "translated text"}}, ...]
3. Do NOT add markdown formatting, explanations, or any extra text. Just the JSON array.
4. Keep translations natural and concise for video subtitles.
5. If the input is already in {lang_name}, keep it as-is."""

            max_retries = 3
            for attempt in range(max_retries):
                try:
                    response = await client.chat.completions.create(
                        model="kimi-k2.6",
                        messages=[
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": segments_text},
                        ],
                        extra_body={"thinking": {"type": "disabled"}},
                        max_tokens=4096,
                    )

                    raw = response.choices[0].message.content.strip()

                    if "```" in raw:
                        json_match = raw.split("```")[1]
                        if json_match.startswith("json"):
                            json_match = json_match[4:]
                        raw = json_match.strip()
                        
                    # Extract JSON array using regex if possible
                    import re
                    match = re.search(r'\[.*\]', raw, re.DOTALL)
                    if match:
                        raw = match.group(0)

                    try:
                        translated_batch = json.loads(raw)
                    except Exception as parse_e:
                        logger.error(f"[Job {job_id}] JSON Parse Error: {parse_e}. Raw text: {repr(raw)}")
                        raise parse_e

                    batch_result = []
                    for j, item in enumerate(translated_batch):
                        if j < len(batch):
                            batch_result.append({
                                "start": batch[j]["start"],
                                "end": batch[j]["end"],
                                "text": item.get("text", batch[j]["text"]),
                                "original": batch[j]["text"],
                            })
                    return batch_result

                except Exception as e:
                    if "429" in str(e) or "Rate limit" in str(e):
                        if attempt < max_retries - 1:
                            logger.warning(f"[Job {job_id}] Batch {batch_num} rate limited. Retrying in 2s...")
                            await asyncio.sleep(2)
                            continue
                    logger.error(f"[Job {job_id}] Batch {batch_num} translation error: {e}")
                    return [{**seg, "original": seg["text"]} for seg in batch]
                    
            # Fallback if all retries fail
            return [{**seg, "original": seg["text"]} for seg in batch]

    # Create tasks for all batches
    tasks = []
    total_batches = (len(segments) + BATCH_SIZE - 1) // BATCH_SIZE
    for i in range(0, len(segments), BATCH_SIZE):
        batch = segments[i : i + BATCH_SIZE]
        batch_num = i // BATCH_SIZE + 1
        tasks.append(_translate_batch(batch, batch_num, total_batches))
        
    results = await asyncio.gather(*tasks)
    
    # Flatten the list of lists
    translated = [item for sublist in results for item in sublist]

    logger.info(
        f"[Job {job_id}] Translation complete: "
        f"{len(translated)}/{len(segments)} segments translated"
    )
    return translated


async def generate_tweet_text(
    title: str,
    segments: list[dict],
    job_id: int = 0,
    target_language: str = "vi",
) -> str:
    """
    Use Kimi to generate an engaging tweet for the translated video.
    """
    client = _get_kimi_client()
    preview = " ".join(s["text"] for s in segments[:5])

    lang_names = {
        "vi": "Vietnamese",
        "en": "English",
        "zh": "Chinese",
        "ja": "Japanese",
        "ko": "Korean",
    }
    lang_name = lang_names.get(target_language, target_language)

    try:
        response = await client.chat.completions.create(
            model="kimi-k2.6",
            messages=[
                {
                    "role": "system",
                    "content": (
                        f"You are a social media expert. Generate a short, engaging tweet "
                        f"in {lang_name} for a translated video. Include relevant emojis and "
                        f"hashtags. Keep it under 250 characters. Do NOT use quotes around the tweet."
                    ),
                },
                {
                    "role": "user",
                    "content": f"Video title: {title}\nContent preview: {preview}",
                },
            ],
            extra_body={"thinking": {"type": "disabled"}},
            max_tokens=200,
        )
        tweet = response.choices[0].message.content.strip().strip('"')
        logger.info(f"[Job {job_id}] Generated tweet: {tweet[:80]}...")
        return tweet

    except Exception as e:
        logger.error(f"[Job {job_id}] Tweet generation failed: {e}")
        return f"🎬 {title[:200]} #ContentBridge #HermesAgent"
