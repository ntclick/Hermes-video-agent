import asyncio
import logging
import os
import json
from pathlib import Path
from playwright.async_api import async_playwright

logger = logging.getLogger("content-bridge.publisher")


async def publish_to_x(
    video_path: str,
    tweet_text: str,
    job_id: int,
    x_cookies_json: str | None = None,
) -> dict:
    """
    Upload video and create tweet on X using Playwright headlessly.

    Args:
        video_path: Path to rendered video file
        tweet_text: Tweet text content
        job_id: For logging
        x_cookies_json: JSON string of exported X cookies

    Returns:
        dict with tweet_id and tweet_url
    """
    logger.info(f"[Job {job_id}] Publishing to X using Playwright...")

    file_size = os.path.getsize(video_path)
    logger.info(f"[Job {job_id}] Video size: {file_size / (1024*1024):.1f} MB")

    if x_cookies_json:
        cookies_str = x_cookies_json
    else:
        cookies_file = Path(os.getenv("X_COOKIES_PATH", "/opt/content-bridge/data/x_cookies.json"))
        if not cookies_file.exists():
            raise ValueError("Twitter cookies JSON not found in settings or provided to job.")
        cookies_str = cookies_file.read_text(encoding="utf-8")

    try:
        cookies_list = json.loads(cookies_str)
        pw_cookies = []
        for c in cookies_list:
            # Playwright requires strict schema for cookies
            if "name" in c and "value" in c:
                cookie = {
                    "name": c["name"],
                    "value": c["value"],
                    "domain": c.get("domain", ".x.com"),
                    "path": c.get("path", "/"),
                }
                # Preserve secure / httpOnly / sameSite — critical for auth cookies
                if c.get("secure"):
                    cookie["secure"] = True
                if c.get("httpOnly"):
                    cookie["httpOnly"] = True
                if c.get("sameSite"):
                    raw_ss = str(c["sameSite"]).capitalize()
                    if raw_ss in ("Strict", "Lax", "None"):
                        cookie["sameSite"] = raw_ss
                exp = c.get("expirationDate") or c.get("expiry") or c.get("expires")
                if exp:
                    try:
                        cookie["expires"] = int(float(exp))
                    except (ValueError, TypeError):
                        pass
                pw_cookies.append(cookie)
    except Exception as e:
        raise ValueError(f"Failed to parse X cookies JSON: {e}")

    if not pw_cookies:
         raise ValueError("Parsed X cookies list is empty or invalid.")

    async def _upload_and_tweet():
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context(
                viewport={"width": 1280, "height": 720},
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            )
            await context.add_cookies(pw_cookies)

            page = await context.new_page()
            logger.info(f"[Job {job_id}] Navigating to compose tweet modal...")
            
            try:
                await page.goto("https://x.com/compose/tweet", wait_until="domcontentloaded", timeout=60000)
            except Exception as e:
                logger.error(f"[Job {job_id}] Failed to load X: {e}")
                await browser.close()
                raise ValueError(f"Failed to load X.com: {e}")

            # Upload video file FIRST (before typing text)
            logger.info(f"[Job {job_id}] Uploading video file...")
            try:
                file_input_selector = "input[type='file']"
                await page.set_input_files(file_input_selector, video_path)
            except Exception as e:
                await page.screenshot(path=str(Path(video_path).parent / "error_upload.png"))
                await browser.close()
                raise ValueError(f"Could not interact with file input: {e}")

            # Wait a moment for upload UI to appear
            await page.wait_for_timeout(2000)

            # Type tweet text using click + keyboard (contenteditable div)
            logger.info(f"[Job {job_id}] Typing tweet text...")
            try:
                textarea_selector = "[data-testid='tweetTextarea_0']"
                await page.wait_for_selector(textarea_selector, timeout=15000)
                await page.click(textarea_selector)
                await page.wait_for_timeout(500)
                await page.keyboard.type(tweet_text, delay=20)
            except Exception as e:
                await page.screenshot(path=str(Path(video_path).parent / "error_typing.png"))
                await browser.close()
                raise ValueError(f"Could not type tweet text: {e}")

            # Wait for video upload processing to complete
            logger.info(f"[Job {job_id}] Waiting for video attachment processing...")
            try:
                # Wait for the post button to become enabled (video done processing)
                active_button = "[data-testid='tweetButton']:not([aria-disabled='true'])"
                await page.wait_for_selector(active_button, timeout=180000)
                await page.wait_for_timeout(2000)
            except Exception as e:
                logger.warning(f"[Job {job_id}] Timeout waiting for video to process: {e}")
                await page.screenshot(path=str(Path(video_path).parent / "error_upload_timeout.png"))

            # Click post button — use JS click as fallback if button is tricky
            logger.info(f"[Job {job_id}] Clicking Post button...")
            try:
                await page.click("[data-testid='tweetButton']", timeout=10000)
            except Exception:
                # Force click via JavaScript
                logger.warning(f"[Job {job_id}] Normal click failed, trying JS click...")
                await page.evaluate("document.querySelector('[data-testid=\"tweetButton\"]')?.click()")

            # Wait for success toast notification
            logger.info(f"[Job {job_id}] Waiting for success confirmation...")
            tweet_id = "unknown"
            tweet_url = ""
            try:
                toast_link = "[data-testid='toast'] a"
                await page.wait_for_selector(toast_link, timeout=30000)
                href = await page.get_attribute(toast_link, "href")
                if href:
                    tweet_url = f"https://x.com{href}" if href.startswith("/") else href
                    tweet_id = tweet_url.split("/")[-1]
            except Exception as e:
                logger.warning(f"[Job {job_id}] Could not catch success toast: {e}")
                await page.screenshot(path=str(Path(video_path).parent / "post_result.png"))

            await browser.close()
            
            if not tweet_url:
                tweet_url = "https://x.com/home"

            logger.info(f"[Job {job_id}] Playwright Publish sequence complete.")
            return {
                "tweet_id": tweet_id,
                "tweet_url": tweet_url,
                "media_id": "playwright_bypass",
            }

    return await _upload_and_tweet()



