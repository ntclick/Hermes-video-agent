"""
Downloader Service — Autonomous Content Bridge
Downloads videos from YouTube, TikTok, Douyin using yt-dlp.
Uses Playwright headless browser as fallback for Douyin's JS anti-bot.
"""
import asyncio
import json
import logging
import os
import re
import tempfile
from pathlib import Path

from backend.config import get_settings
from backend.models import Platform

logger = logging.getLogger("content-bridge.downloader")


def detect_platform(url: str) -> Platform:
    """Detect the source platform from URL."""
    url_lower = url.lower()
    if "youtube.com" in url_lower or "youtu.be" in url_lower:
        return Platform.YOUTUBE
    elif "tiktok.com" in url_lower:
        return Platform.TIKTOK
    elif "douyin.com" in url_lower:
        return Platform.DOUYIN
    return Platform.OTHER


# ── Playwright Cookie Helper ─────────────────────────────────

async def _get_fresh_douyin_cookies_via_playwright(url: str, stored_cookies_netscape: str | None, job_id: int) -> str:
    """
    Launch headless Chromium, navigate to the Douyin URL, solve JS challenge,
    and return a Netscape-format cookie file path with fresh cookies.
    """
    from playwright.async_api import async_playwright

    logger.info(f"[Job {job_id}] 🌐 Launching Playwright headless browser for Douyin...")

    cookie_file = tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False, encoding='utf-8')
    cookie_file_path = cookie_file.name

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-dev-shm-usage",
                "--disable-blink-features=AutomationControlled",
            ],
        )
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                       "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            viewport={"width": 1920, "height": 1080},
            locale="zh-CN",
        )

        # Inject stored cookies if available
        if stored_cookies_netscape:
            pw_cookies = _parse_cookies_to_playwright(stored_cookies_netscape)
            if pw_cookies:
                await context.add_cookies(pw_cookies)
                logger.info(f"[Job {job_id}] Injected {len(pw_cookies)} stored cookies into browser")

        page = await context.new_page()

        # Stealth: remove navigator.webdriver flag
        await page.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', { get: () => false });
        """)

        try:
            logger.info(f"[Job {job_id}] Navigating to {url}...")
            await page.goto(url, wait_until="domcontentloaded", timeout=30000)

            # Wait for JS challenge to resolve — Douyin typically finishes within 5-10s
            logger.info(f"[Job {job_id}] Waiting for JS anti-bot challenge to resolve...")
            await page.wait_for_timeout(8000)

            # Try to wait for video element or specific content as a signal
            try:
                await page.wait_for_selector("video, .xgplayer, [data-e2e='video-player']", timeout=15000)
                logger.info(f"[Job {job_id}] ✅ Video player detected — page loaded successfully")
            except Exception:
                logger.warning(f"[Job {job_id}] Video player not detected, but continuing with cookies...")

        except Exception as e:
            logger.warning(f"[Job {job_id}] Page navigation warning: {e}")

        # Extract all cookies from the browser context
        browser_cookies = await context.cookies()
        logger.info(f"[Job {job_id}] Extracted {len(browser_cookies)} cookies from browser")

        await browser.close()

    # Convert Playwright cookies to Netscape format
    lines = ["# Netscape HTTP Cookie File"]
    for c in browser_cookies:
        domain = c.get("domain", ".douyin.com")
        include_subdomains = "TRUE" if domain.startswith(".") else "FALSE"
        path = c.get("path", "/")
        secure = "TRUE" if c.get("secure") else "FALSE"
        expiry = int(c.get("expires", 0))
        if expiry < 0:
            expiry = 0
        name = c.get("name", "")
        value = c.get("value", "")
        if not name:
            continue
        lines.append(f"{domain}\t{include_subdomains}\t{path}\t{secure}\t{expiry}\t{name}\t{value}")

    netscape_text = "\n".join(lines) + "\n"
    cookie_file.write(netscape_text)
    cookie_file.close()

    logger.info(f"[Job {job_id}] ✅ Fresh Douyin cookies saved to {cookie_file_path} ({len(browser_cookies)} cookies)")
    return cookie_file_path


def _parse_cookies_to_playwright(cookie_text: str) -> list[dict]:
    """Convert Netscape cookie text or JSON cookie array to Playwright cookie format."""
    cookie_text = cookie_text.strip()
    
    # Try parsing as JSON first
    if cookie_text.startswith("[") and cookie_text.endswith("]"):
        try:
            json_cookies = json.loads(cookie_text)
            pw_cookies = []
            for c in json_cookies:
                pw_c = {
                    "name": c.get("name", ""),
                    "value": c.get("value", ""),
                    "domain": c.get("domain", ""),
                    "path": c.get("path", "/"),
                }
                if "secure" in c:
                    pw_c["secure"] = bool(c["secure"])
                if "httpOnly" in c:
                    pw_c["httpOnly"] = bool(c["httpOnly"])
                if "expirationDate" in c:
                    pw_c["expires"] = int(c["expirationDate"])
                elif "expires" in c:
                    try:
                        pw_c["expires"] = int(c["expires"])
                    except Exception:
                        pass
                if pw_c["name"] and pw_c["domain"]:
                    pw_cookies.append(pw_c)
            return pw_cookies
        except Exception as e:
            logger.warning(f"Failed to parse JSON cookies: {e}")

    # Fallback to Netscape parsing
    cookies = []
    for line in cookie_text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split("\t")
        if len(parts) >= 7:
            domain, _, path, secure, expires, name, value = parts[0], parts[1], parts[2], parts[3], parts[4], parts[5], parts[6]
            cookie = {
                "name": name,
                "value": value,
                "domain": domain,
                "path": path,
                "secure": secure == "TRUE",
                "httpOnly": False,
            }
            try:
                exp = int(expires)
                if exp > 0:
                    cookie["expires"] = exp
            except ValueError:
                pass
            cookies.append(cookie)
    return cookies


# ── Main Download Function ────────────────────────────────────

async def _download_douyin_direct(url: str, job_id: int, output_dir: Path, settings) -> dict:
    """
    Use Playwright to intercept the raw MP4 video stream from Douyin directly,
    bypassing yt-dlp which gets blocked by WAF signatures.
    """
    from playwright.async_api import async_playwright
    import httpx

    logger.info(f"[Job {job_id}] 🌐 Launching Playwright to intercept Douyin stream...")

    video_url = None
    title = f"douyin_{job_id}"

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-dev-shm-usage",
                "--disable-blink-features=AutomationControlled",
            ],
        )
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            viewport={"width": 1920, "height": 1080},
            locale="zh-CN",
        )

        # Inject stored cookies if available
        if settings.douyin_cookies:
            stored_cookies_netscape = settings.douyin_cookies.replace("\\n", "\n")
            pw_cookies = _parse_cookies_to_playwright(stored_cookies_netscape)
            if pw_cookies:
                await context.add_cookies(pw_cookies)
                logger.info(f"[Job {job_id}] Injected {len(pw_cookies)} stored cookies into browser")

        page = await context.new_page()

        # Stealth
        await page.add_init_script("Object.defineProperty(navigator, 'webdriver', { get: () => false });")

        async def handle_response(response):
            nonlocal video_url
            if not video_url and response.status in (200, 206):
                req_type = response.request.resource_type
                ct = response.headers.get("content-type", "")
                url_lower = response.url.lower()
                
                # Check if it's a media request, OR looks like a video chunk based on content-type/url
                if req_type == "media" or "video" in ct or "audio" in ct or "application/octet-stream" in ct:
                    if "douyinvod.com" in url_lower or "video" in url_lower or req_type == "media":
                        video_url = response.url
                        logger.info(f"[Job {job_id}] 🎯 Intercepted video URL ({req_type}): {video_url[:100]}...")

        page.on("response", handle_response)

        try:
            logger.info(f"[Job {job_id}] Navigating to {url}...")
            await page.goto(url, wait_until="domcontentloaded", timeout=30000)

            # Wait for JS challenge and video load
            logger.info(f"[Job {job_id}] Waiting 10s for page to render and requests to fire...")
            await page.wait_for_timeout(10000)

            # Attempt to get the page title
            try:
                page_title = await page.title()
                if page_title and "douyin" not in page_title.lower() and "captcha" not in page_title.lower():
                    title = page_title.replace(" - 抖音", "").strip()
            except Exception:
                pass

        except Exception as e:
            logger.warning(f"[Job {job_id}] Page navigation warning: {e}")

        # Fallback if interception failed: try DOM extract
        if not video_url:
            logger.warning(f"[Job {job_id}] No video request intercepted, extracting from DOM...")
            try:
                video_url = await page.evaluate('''() => {
                    const vid = document.querySelector('video');
                    if (vid) {
                        return vid.querySelector('source') ? vid.querySelector('source').src : vid.src;
                    }
                    return null;
                }''')
            except Exception as e:
                logger.warning(f"[Job {job_id}] DOM extraction failed: {e}")

        await browser.close()

    if not video_url:
        raise RuntimeError("Failed to intercept Douyin video URL. Douyin might have blocked the request or the video is private.")

    if video_url.startswith("//"):
        video_url = "https:" + video_url

    # Download the intercepted video URL
    import re
    safe_title = re.sub(r'[\\/*?:"<>|]', "_", title[:80])
    output_path = output_dir / f"{safe_title}.mp4"
    logger.info(f"[Job {job_id}] 📥 Downloading raw video stream to {output_path}...")

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Referer": "https://www.douyin.com/",
    }

    try:
        import httpx
        async with httpx.AsyncClient(follow_redirects=True) as client:
            async with client.stream("GET", video_url, headers=headers) as r:
                r.raise_for_status()
                with open(output_path, "wb") as f:
                    async for chunk in r.aiter_bytes(chunk_size=8192):
                        f.write(chunk)
    except Exception as e:
        raise RuntimeError(f"Failed to download intercepted video stream: {e}")

    logger.info(f"[Job {job_id}] ✅ Douyin direct download complete: {output_path}")

    # Generate an info.json for consistency
    info_dict = {"title": title, "duration": None, "thumbnail": None}
    with open(output_dir / f"{safe_title}.info.json", "w", encoding="utf-8") as f:
        json.dump(info_dict, f, ensure_ascii=False)

    return {
        "video_path": str(output_path),
        "title": title,
        "duration": None,
        "thumbnail_url": None,
        "platform": Platform.DOUYIN,
    }


# ── Main Download Function ────────────────────────────────────

async def download_video(url: str, job_id: int) -> dict:
    """
    Download video using yt-dlp (YouTube/TikTok) or Playwright direct intercept (Douyin).
    """
    from backend.models import Job
    from backend.database import get_session_factory
    from backend.config import get_job_settings

    factory = get_session_factory()
    async with factory() as session:
        job = await session.get(Job, job_id)
        if job and job.user_keys_json:
            settings = get_job_settings(job.user_keys_json)
        else:
            settings = get_settings()

    output_dir = settings.downloads_dir / str(job_id)
    output_dir.mkdir(parents=True, exist_ok=True)
    output_template = str(output_dir / "%(title).80s.%(ext)s")

    platform = detect_platform(url)

    # Pre-process Douyin URLs if they have modal_id
    if platform == Platform.DOUYIN and "modal_id=" in url:
        match = re.search(r"modal_id=(\d+)", url)
        if match:
            video_id = match.group(1)
            url = f"https://www.douyin.com/video/{video_id}"
            logger.info(f"[Job {job_id}] Rewrote Douyin modal URL to standard format: {url}")

    logger.info(f"[Job {job_id}] Downloading from {platform.value}: {url}")

    # For Douyin, bypass yt-dlp entirely due to aggressive anti-bot blocking
    if platform == Platform.DOUYIN:
        return await _download_douyin_direct(url, job_id, output_dir, settings)

    # Build yt-dlp command for other platforms
    cmd = [
        "yt-dlp",
        "--no-playlist",
        "--format", "bestvideo[height<=1080][ext=mp4]+bestaudio[ext=m4a]/best[height<=1080][ext=mp4]/best",
        "--merge-output-format", "mp4",
        "--output", output_template,
        "--write-info-json",
        "--write-thumbnail",
        "--no-overwrites",
        "--socket-timeout", "30",
        "--retries", "3",
    ]

    if platform == Platform.TIKTOK:
        cmd.extend(["--extractor-args", "tiktok:api_hostname=api22-normal-c-useast2a.tiktokv.com"])

    cmd.append(url)

    logger.info(f"[Job {job_id}] Running: {' '.join(cmd)}")

    process = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await process.communicate()

    stdout_str = stdout.decode("utf-8", errors="replace")
    stderr_str = stderr.decode("utf-8", errors="replace")

    if process.returncode != 0:
        error_msg = stderr_str or stdout_str
        logger.error(f"[Job {job_id}] yt-dlp failed: {error_msg}")
        raise RuntimeError(f"Download failed: {error_msg[:500]}")

    logger.info(f"[Job {job_id}] Download complete")

    # Find downloaded files
    video_files = list(output_dir.glob("*.mp4"))
    if not video_files:
        video_files = list(output_dir.glob("*.mkv")) + list(output_dir.glob("*.webm"))

    if not video_files:
        raise RuntimeError(f"No video file found in {output_dir}")

    video_path = video_files[0]

    # Parse metadata from info.json
    info_files = list(output_dir.glob("*.info.json"))
    metadata = {"title": video_path.stem, "duration": None, "thumbnail_url": None}

    if info_files:
        try:
            with open(info_files[0], "r", encoding="utf-8") as f:
                info = json.load(f)
            metadata["title"] = info.get("title", video_path.stem)
            metadata["duration"] = info.get("duration")
            metadata["thumbnail_url"] = info.get("thumbnail")
        except Exception as e:
            logger.warning(f"[Job {job_id}] Could not parse info.json: {e}")

    result = {
        "video_path": str(video_path),
        "title": metadata["title"],
        "duration": metadata["duration"],
        "thumbnail_url": metadata["thumbnail_url"],
        "platform": platform,
    }

    logger.info(f"[Job {job_id}] Downloaded: {result['title']} ({result['duration']}s)")
    return result

