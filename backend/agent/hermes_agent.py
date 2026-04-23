"""
Hermes Agent — Autonomous Content Bridge
Lightweight agent framework using Hermes model (via OpenRouter/compatible API)
with function calling to orchestrate the content pipeline.
"""
import json
import logging
from openai import AsyncOpenAI

from backend.config import get_settings
from backend.agent.tools import TOOLS, execute_tool

logger = logging.getLogger("content-bridge.agent")

SYSTEM_PROMPT = """You are the Hermes Content Bridge Agent — an autonomous AI agent specialized in cross-platform video content translation, creative remixing, and distribution.

Your mission: Help users automatically download videos from platforms (YouTube, TikTok, Douyin), translate them, add subtitles, generate AI cover videos, and publish to X (Twitter).

You have access to these tools:

CORE PIPELINE:
- download_video: Download videos from any supported platform
- transcribe_video: Convert speech to text using Whisper AI
- translate_content: Translate text using Kimi K2.5
- render_with_subtitles: Burn subtitles into video using FFmpeg
- publish_to_x: Post the final video to X/Twitter
- analyze_content: Analyze content for best publishing strategy

CREATIVE COVER VIDEO (NEW):
- rewrite_script: Analyze a video's content and create a creative visual script with scene breakdowns and AI image prompts
- generate_scene_images: Generate stunning AI images for each scene using fal.ai FLUX model
- compose_cover_video: Compose the AI images into a cover video with Ken Burns effects, original audio, and subtitles

When generating a cover video:
1. Use rewrite_script with the video summary and transcript to create scene prompts
2. Use generate_scene_images with the scenes and job_id to create AI images
3. Use compose_cover_video with the scenes directory, audio, and subtitles to create the final cover

Always explain what you're doing at each step. Be concise but informative.
If any step fails, explain the error and suggest solutions."""


class HermesAgent:
    """
    Autonomous agent powered by Hermes model with tool-calling capabilities.
    Uses OpenAI-compatible API (works with OpenRouter, vLLM, etc.)
    """

    def __init__(self):
        settings = get_settings()
        provider = (settings.hermes_provider or "openrouter").lower()

        if provider == "kimi":
            api_key = settings.kimi_api_key
            base_url = settings.kimi_base_url
        else:
            # "openrouter" or "custom" — both use hermes_* fields
            api_key = settings.hermes_api_key
            base_url = settings.hermes_base_url

        self.provider = provider
        self.client = AsyncOpenAI(api_key=api_key, base_url=base_url)
        self.model = settings.hermes_model
        self.max_iterations = 10  # Safety limit for tool-call loops
        logger.info(f"HermesAgent initialized with provider={provider} model={self.model}")

    async def process_message(
        self,
        user_message: str,
        conversation_history: list[dict] | None = None,
        job_id: int | None = None,
    ) -> dict:
        """
        Process a user message through the agent.

        Args:
            user_message: The user's input
            conversation_history: Previous messages for context
            job_id: Optional job ID to pass to tools

        Returns:
            dict with 'response' (str) and 'tool_calls' (list of executed tools)
        """
        messages = [{"role": "system", "content": SYSTEM_PROMPT}]

        if conversation_history:
            messages.extend(conversation_history)

        messages.append({"role": "user", "content": user_message})

        executed_tools = []
        iterations = 0

        while iterations < self.max_iterations:
            iterations += 1
            logger.info(f"Agent iteration {iterations}")

            try:
                response = await self.client.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    tools=TOOLS,
                    tool_choice="auto",
                    max_tokens=2048,
                )
            except Exception as e:
                logger.error(f"Agent API call failed: {e}")
                return {
                    "response": f"I encountered an error connecting to the AI model: {str(e)}",
                    "tool_calls": executed_tools,
                }

            choice = response.choices[0]
            assistant_message = choice.message

            # Append assistant's response to conversation
            messages.append(assistant_message.model_dump())

            # Check if there are tool calls
            if assistant_message.tool_calls:
                for tool_call in assistant_message.tool_calls:
                    fn_name = tool_call.function.name
                    fn_args = json.loads(tool_call.function.arguments)

                    # Inject job_id if available and not provided
                    if job_id and "job_id" not in fn_args:
                        fn_args["job_id"] = job_id

                    logger.info(f"Agent calling tool: {fn_name}({fn_args})")

                    try:
                        result = await execute_tool(fn_name, fn_args)
                        result_str = json.dumps(result, default=str, ensure_ascii=False)
                    except Exception as e:
                        logger.error(f"Tool {fn_name} failed: {e}")
                        result_str = json.dumps({"error": str(e)})

                    executed_tools.append({
                        "tool": fn_name,
                        "args": fn_args,
                        "result": result_str[:1000],  # Truncate for logging
                    })

                    # Add tool result to messages
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": result_str,
                    })

                # Continue loop to let agent process tool results
                continue

            # No tool calls — agent has final response
            return {
                "response": assistant_message.content or "",
                "tool_calls": executed_tools,
            }

        # Max iterations reached
        return {
            "response": "I've reached the maximum number of steps. The pipeline may be partially complete.",
            "tool_calls": executed_tools,
        }

    async def process_url(self, url: str, target_language: str = "vi") -> dict:
        """
        Convenience method: Process a video URL through the full pipeline.

        Returns: Agent response with all tool execution details
        """
        message = (
            f"Please process this video URL through the full pipeline:\n"
            f"URL: {url}\n"
            f"Target language: {target_language}\n"
            f"Steps: Download → Transcribe → Translate → Render subtitles → Publish to X"
        )
        return await self.process_message(message)
