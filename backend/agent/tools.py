"""
Hermes Agent Tools — Autonomous Content Bridge
Defines the tool functions that the Hermes Agent can call.
"""
import logging
from typing import Any

logger = logging.getLogger("content-bridge.agent.tools")

# Tool definitions in OpenAI function-calling format
TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "download_video",
            "description": "Download a video from YouTube, TikTok, or Douyin given a URL. Returns video metadata and file path.",
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {
                        "type": "string",
                        "description": "The video URL to download (YouTube, TikTok, or Douyin)",
                    },
                },
                "required": ["url"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "transcribe_video",
            "description": "Transcribe the audio from a downloaded video using Whisper AI. Returns timestamped transcript segments.",
            "parameters": {
                "type": "object",
                "properties": {
                    "video_path": {
                        "type": "string",
                        "description": "Path to the video file to transcribe",
                    },
                    "job_id": {
                        "type": "integer",
                        "description": "The job ID for tracking",
                    },
                },
                "required": ["video_path", "job_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "translate_content",
            "description": "Translate transcribed text segments to a target language using Kimi K2.5 AI.",
            "parameters": {
                "type": "object",
                "properties": {
                    "segments": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "start": {"type": "number"},
                                "end": {"type": "number"},
                                "text": {"type": "string"},
                            },
                        },
                        "description": "List of transcript segments with timestamps",
                    },
                    "target_language": {
                        "type": "string",
                        "description": "ISO 639-1 language code (e.g., 'vi' for Vietnamese)",
                        "default": "vi",
                    },
                },
                "required": ["segments"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "render_with_subtitles",
            "description": "Burn translated subtitles into the video using FFmpeg. Optimizes for Twitter upload.",
            "parameters": {
                "type": "object",
                "properties": {
                    "video_path": {
                        "type": "string",
                        "description": "Source video file path",
                    },
                    "subtitle_path": {
                        "type": "string",
                        "description": "Subtitle file path (.srt or .ass)",
                    },
                    "job_id": {
                        "type": "integer",
                        "description": "The job ID for tracking",
                    },
                },
                "required": ["video_path", "subtitle_path", "job_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "publish_to_x",
            "description": "Upload a video and publish a tweet on X (Twitter).",
            "parameters": {
                "type": "object",
                "properties": {
                    "video_path": {
                        "type": "string",
                        "description": "Path to the video file to upload",
                    },
                    "tweet_text": {
                        "type": "string",
                        "description": "The tweet text to post with the video",
                    },
                    "job_id": {
                        "type": "integer",
                        "description": "The job ID for tracking",
                    },
                },
                "required": ["video_path", "tweet_text", "job_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "analyze_content",
            "description": "Analyze video content and suggest the best approach for translation and publishing.",
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {
                        "type": "string",
                        "description": "Video title",
                    },
                    "transcript": {
                        "type": "string",
                        "description": "Video transcript text",
                    },
                },
                "required": ["title", "transcript"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "rewrite_script",
            "description": "Rewrite a creative script from a video's summary and transcript. Returns a list of scenes with narration text and image prompts for AI image generation.",
            "parameters": {
                "type": "object",
                "properties": {
                    "summary": {
                        "type": "string",
                        "description": "AI-generated video summary",
                    },
                    "transcript": {
                        "type": "string",
                        "description": "Full transcript text of the video",
                    },
                    "style": {
                        "type": "string",
                        "description": "Visual style: cinematic, anime, photorealistic, documentary",
                        "default": "cinematic",
                    },
                    "num_scenes": {
                        "type": "integer",
                        "description": "Number of scenes to generate (3-8)",
                        "default": 5,
                    },
                },
                "required": ["summary", "transcript"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "generate_scene_images",
            "description": "Generate AI images for each scene using fal.ai FLUX model. Takes scene prompts from rewrite_script output.",
            "parameters": {
                "type": "object",
                "properties": {
                    "scenes": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "scene": {"type": "integer"},
                                "image_prompt": {"type": "string"},
                            },
                        },
                        "description": "List of scene objects with image_prompt field",
                    },
                    "job_id": {
                        "type": "integer",
                        "description": "The job ID for tracking",
                    },
                    "style": {
                        "type": "string",
                        "description": "Visual style for generation",
                        "default": "cinematic",
                    },
                },
                "required": ["scenes", "job_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "compose_cover_video",
            "description": "Compose AI-generated scene images into a cover video with Ken Burns effects, original audio, and subtitles.",
            "parameters": {
                "type": "object",
                "properties": {
                    "scenes_dir": {
                        "type": "string",
                        "description": "Directory containing the AI scene images",
                    },
                    "audio_path": {
                        "type": "string",
                        "description": "Path to the original audio file",
                    },
                    "subtitle_path": {
                        "type": "string",
                        "description": "Path to subtitle file (.ass or .srt)",
                    },
                    "job_id": {
                        "type": "integer",
                        "description": "The job ID for tracking",
                    },
                },
                "required": ["scenes_dir", "audio_path", "job_id"],
            },
        },
    },
]


async def execute_tool(name: str, arguments: dict) -> Any:
    """Execute a tool function by name with given arguments."""
    from backend.services.downloader import download_video
    from backend.services.transcriber import full_transcribe
    from backend.services.translator import translate_segments, generate_tweet_text
    from backend.services.subtitle import generate_dual_subtitles
    from backend.services.renderer import render_video
    from backend.services.publisher import publish_to_x as _publish
    from backend.services.fal_generator import generate_all_scenes
    from backend.services.cover_composer import compose_cover_video as _compose

    logger.info(f"Executing tool: {name} with args: {list(arguments.keys())}")

    if name == "download_video":
        return await download_video(arguments["url"], arguments.get("job_id", 0))

    elif name == "transcribe_video":
        audio_path, segments = await full_transcribe(
            arguments["video_path"], arguments["job_id"]
        )
        return {"audio_path": audio_path, "segments": segments}

    elif name == "translate_content":
        return await translate_segments(
            arguments["segments"],
            arguments.get("target_language", "vi"),
            arguments.get("job_id", 0),
        )

    elif name == "render_with_subtitles":
        return await render_video(
            arguments["video_path"],
            arguments["subtitle_path"],
            arguments["job_id"],
        )

    elif name == "publish_to_x":
        return await _publish(
            arguments["video_path"],
            arguments["tweet_text"],
            arguments["job_id"],
        )

    elif name == "analyze_content":
        # Use Kimi to analyze content
        from openai import AsyncOpenAI
        from backend.config import get_settings
        settings = get_settings()
        client = AsyncOpenAI(
            api_key=settings.kimi_api_key,
            base_url=settings.kimi_base_url,
        )
        response = await client.chat.completions.create(
            model="moonshot-v1-8k",
            messages=[
                {"role": "system", "content": "Analyze this video content. Suggest target audience, best hashtags, and posting time."},
                {"role": "user", "content": f"Title: {arguments['title']}\nTranscript: {arguments['transcript'][:2000]}"},
            ],
            max_tokens=500,
        )
        return {"analysis": response.choices[0].message.content}

    elif name == "rewrite_script":
        # Use Kimi K2.6 for script rewriting
        from openai import AsyncOpenAI
        from backend.config import get_settings
        import json
        settings = get_settings()
        client = AsyncOpenAI(
            api_key=settings.kimi_api_key,
            base_url=settings.kimi_base_url,
        )
        
        num_scenes = arguments.get("num_scenes", 5)
        style = arguments.get("style", "cinematic")
        target_lang = arguments.get("target_language", "Vietnamese")
        
        prompt = f"""Based on this video content, create a {style} visual script with exactly {num_scenes} scenes.

VIDEO SUMMARY:
{arguments['summary'][:1000]}

TRANSCRIPT (partial):
{arguments['transcript'][:2000]}

Return a JSON array of scenes. Each scene must have:
- "scene": scene number (1-{num_scenes})
- "narration": what is being said/shown in this scene (1-2 sentences). MUST BE WRITTEN IN {target_lang.upper()}.
- "image_prompt": a detailed prompt in English to generate an AI image for this scene. Be specific about composition, lighting, subjects, mood. Do NOT mention any text or words in the image.
- "duration": suggested duration in seconds (3-8)

Return ONLY the JSON array, no other text."""
        
        response = await client.chat.completions.create(
            model="kimi-k2.6",
            messages=[
                {"role": "system", "content": f"You are a creative director specializing in {style} visual storytelling. Generate scene breakdowns for AI image generation. The output narration MUST be in {target_lang.upper()}."},
                {"role": "user", "content": prompt},
            ],
            extra_body={"thinking": {"type": "disabled"}},
            max_tokens=2000,
        )
        
        raw = response.choices[0].message.content.strip()
        # Try to extract JSON from the response
        if "```json" in raw:
            raw = raw.split("```json")[1].split("```")[0].strip()
        elif "```" in raw:
            raw = raw.split("```")[1].split("```")[0].strip()
        
        try:
            scenes = json.loads(raw)
        except json.JSONDecodeError:
            # Try to find array in the text
            import re
            match = re.search(r'\[.*\]', raw, re.DOTALL)
            if match:
                scenes = json.loads(match.group())
            else:
                raise ValueError(f"Failed to parse script JSON from Hermes response: {raw[:200]}")
        
        return {"scenes": scenes, "style": style}

    elif name == "generate_scene_images":
        scenes_dir = await generate_all_scenes(
            arguments["scenes"],
            arguments["job_id"],
            arguments.get("style", "cinematic"),
        )
        return {"scenes_dir": scenes_dir, "count": len(arguments["scenes"])}

    elif name == "compose_cover_video":
        cover_path = await _compose(
            arguments["scenes_dir"],
            arguments["audio_path"],
            arguments.get("subtitle_path", ""),
            arguments["job_id"],
        )
        return {"cover_path": cover_path}

    else:
        raise ValueError(f"Unknown tool: {name}")

