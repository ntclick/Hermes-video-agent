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
import sys
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

async def _try_ytdlp_douyin(url: str, job_id: int, output_dir: Path, cookie_file: str | None) -> dict | None:
    """
    Attempt yt-dlp download for Douyin with a Netscape cookie file.
    Returns result dict on success, None on failure.
    """
    output_template = str(output_dir / "%(title).80s.%(ext)s")
    ua = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    cmd = [
        "yt-dlp",
        "--no-playlist",
        "--format", "bestvideo[height<=1080][ext=mp4]+bestaudio[ext=m4a]/best[height<=1080][ext=mp4]/best",
        "--merge-output-format", "mp4",
        "--output", output_template,
        "--write-info-json",
        "--no-overwrites",
        "--socket-timeout", "30",
        "--retries", "3",
        "--user-agent", ua,
        "--add-header", f"Referer:https://www.douyin.com/",
    ]
    if cookie_file:
        cmd += ["--cookies", cookie_file]
    cmd.append(url)

    logger.info(f"[Job {job_id}] 🔧 Trying yt-dlp with cookies: {' '.join(cmd[:6])}...")
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()

    if proc.returncode != 0:
        err = (stderr or stdout).decode("utf-8", errors="replace")
        logger.warning(f"[Job {job_id}] yt-dlp failed for Douyin: {err[:300]}")
        return None

    video_files = list(output_dir.glob("*.mp4"))
    if not video_files:
        video_files = list(output_dir.glob("*.mkv")) + list(output_dir.glob("*.webm"))
    if not video_files:
        logger.warning(f"[Job {job_id}] yt-dlp succeeded but no video file found")
        return None

    video_path = video_files[0]
    info_files = list(output_dir.glob("*.info.json"))
    title = video_path.stem
    duration = None
    thumbnail_url = None
    if info_files:
        try:
            with open(info_files[0], "r", encoding="utf-8") as f:
                info = json.load(f)
            title = info.get("title", title)
            duration = info.get("duration")
            thumbnail_url = info.get("thumbnail")
        except Exception:
            pass

    logger.info(f"[Job {job_id}] ✅ yt-dlp Douyin success: {title}")
    return {"video_path": str(video_path), "title": title, "duration": duration, "thumbnail_url": thumbnail_url, "platform": Platform.DOUYIN}


async def _download_douyin_direct(url: str, job_id: int, output_dir: Path, settings) -> dict:
    """
    Download Douyin video.
    Strategy:
      1. Get fresh cookies from Playwright (solves JS challenge)
      2. Try yt-dlp with those cookies (fastest + handles HLS/DASH natively)
      3. Fall back to Playwright network interception + FFmpeg download
    """
    from playwright.async_api import async_playwright
    import tempfile

    logger.info(f"[Job {job_id}] 🌐 Launching Playwright (cookie export + stream intercept)...")

    mp4_candidates: list[tuple[int, int, str]] = []  # (priority, content_length, url)
    hls_candidates: list[tuple[int, str]] = []
    title = f"douyin_{job_id}"
    page_url = url
    fresh_cookie_file: str | None = None
    intercepted_url: str | None = None
    use_hls = False
    ua = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

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
            user_agent=ua,
            viewport={"width": 1920, "height": 1080},
            locale="zh-CN",
        )

        if settings.douyin_cookies:
            stored = settings.douyin_cookies.replace("\\n", "\n")
            pw_cookies = _parse_cookies_to_playwright(stored)
            if pw_cookies:
                await context.add_cookies(pw_cookies)
                logger.info(f"[Job {job_id}] Injected {len(pw_cookies)} stored cookies into browser")

        page = await context.new_page()
        await page.add_init_script("Object.defineProperty(navigator, 'webdriver', { get: () => false });")

        async def handle_response(response):
            if response.status not in (200, 206):
                return
            req_type = response.request.resource_type
            ct = response.headers.get("content-type", "")
            resp_url = response.url
            rl = resp_url.lower()

            is_cdn = (
                "douyinvod.com" in rl or "bytecdn.cn" in rl
                or "bytedance.com" in rl or "tiktokcdn.com" in rl
            )
            # Skip individual HLS/DASH segments — we want the manifest
            if ".ts" in rl or ".m4s" in rl:
                return

            is_hls = (
                ".m3u8" in rl
                or "application/x-mpegurl" in ct.lower()
                or "application/vnd.apple.mpegurl" in ct.lower()
            )
            if is_hls:
                hls_candidates.append((0 if is_cdn else 1, resp_url))
                logger.info(f"[Job {job_id}] 📡 HLS manifest: {resp_url[:120]}...")
                return

            if req_type == "media" or "video/mp4" in ct or "video/webm" in ct:
                try:
                    content_length = int(response.headers.get("content-length", "0"))
                except Exception:
                    content_length = 0
                mp4_candidates.append((0 if is_cdn else 1, content_length, resp_url))
                logger.info(f"[Job {job_id}] 📡 MP4 candidate ({content_length//1024}KB): {resp_url[:120]}...")

        page.on("response", handle_response)

        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=30000)
            await page.wait_for_timeout(5000)

            # Trigger video autoplay (headless browsers block it by default)
            try:
                await page.evaluate("""() => {
                    const v = document.querySelector('video');
                    if (v) { v.muted = true; v.play().catch(() => {}); }
                }""")
            except Exception:
                pass

            await page.wait_for_timeout(8000)

            try:
                page_title = await page.title()
                if page_title and "douyin" not in page_title.lower() and "captcha" not in page_title.lower():
                    title = page_title.replace(" - 抖音", "").strip()
            except Exception:
                pass

        except Exception as e:
            logger.warning(f"[Job {job_id}] Page navigation warning: {e}")

        # Export fresh cookies → yt-dlp can use them
        try:
            browser_cookies = await context.cookies()
            lines = ["# Netscape HTTP Cookie File"]
            for c in browser_cookies:
                domain = c.get("domain", ".douyin.com")
                subdomains = "TRUE" if domain.startswith(".") else "FALSE"
                path = c.get("path", "/")
                secure = "TRUE" if c.get("secure") else "FALSE"
                expiry = max(0, int(c.get("expires", 0)))
                name, value = c.get("name", ""), c.get("value", "")
                if name:
                    lines.append(f"{domain}\t{subdomains}\t{path}\t{secure}\t{expiry}\t{name}\t{value}")
            tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False, encoding="utf-8")
            tmp.write("\n".join(lines) + "\n")
            tmp.close()
            fresh_cookie_file = tmp.name
            logger.info(f"[Job {job_id}] 🍪 Exported {len(browser_cookies)} fresh cookies for yt-dlp")
        except Exception as e:
            logger.warning(f"[Job {job_id}] Cookie export failed: {e}")

        # Pick best intercepted URL as fallback
        # Sort: CDN priority first, then largest content-length (filters out small ad clips)
        if mp4_candidates:
            mp4_candidates.sort(key=lambda x: (x[0], -x[1]))
            best = mp4_candidates[0]
            intercepted_url = best[2]
            logger.info(f"[Job {job_id}] 🎯 Intercepted MP4 ({len(mp4_candidates)} candidates, best={best[1]//1024}KB): {intercepted_url[:120]}...")
        elif hls_candidates:
            hls_candidates.sort(key=lambda x: x[0])
            intercepted_url = hls_candidates[0][1]
            use_hls = True
            logger.info(f"[Job {job_id}] 🎯 Intercepted HLS ({len(hls_candidates)} candidates): {intercepted_url[:120]}...")

        if not intercepted_url:
            try:
                intercepted_url = await page.evaluate("""() => {
                    const v = document.querySelector('video');
                    if (v) return v.querySelector('source') ? v.querySelector('source').src : v.src;
                    return null;
                }""")
                if intercepted_url:
                    logger.info(f"[Job {job_id}] DOM fallback URL: {intercepted_url[:120]}...")
            except Exception:
                pass

        await browser.close()

    # ── Phase 2: yt-dlp with fresh cookies (primary) ─────────────────────
    if fresh_cookie_file:
        result = await _try_ytdlp_douyin(url, job_id, output_dir, fresh_cookie_file)
        try:
            os.unlink(fresh_cookie_file)
        except Exception:
            pass
        if result:
            return result
        logger.warning(f"[Job {job_id}] yt-dlp failed, falling back to intercepted URL + FFmpeg...")

    # ── Phase 3: FFmpeg download from intercepted URL (fallback) ──────────
    if not intercepted_url:
        raise RuntimeError("Douyin download failed: yt-dlp gave up and no video URL was intercepted by Playwright.")

    if intercepted_url.startswith("//"):
        intercepted_url = "https:" + intercepted_url

    safe_title = re.sub(r'[\\/*?:"<>|]', "_", title[:80])
    output_path = output_dir / f"{safe_title}.mp4"
    label = "HLS stream" if use_hls else "MP4"
    logger.info(f"[Job {job_id}] 📥 FFmpeg downloading {label} → {output_path}...")

    ffmpeg_cmd = [
        "ffmpeg", "-y",
        "-user_agent", ua,
        "-headers", f"Referer: {page_url}\r\n",
        "-i", intercepted_url,
        "-c", "copy",
        str(output_path),
    ]
    proc = await asyncio.create_subprocess_exec(
        *ffmpeg_cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _, ffmpeg_stderr = await proc.communicate()

    if proc.returncode != 0:
        err = ffmpeg_stderr.decode("utf-8", errors="replace")[-400:]
        raise RuntimeError(f"FFmpeg fallback also failed: {err}")

    logger.info(f"[Job {job_id}] ✅ Douyin direct download complete: {output_path}")

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

    # YouTube: add cookies to avoid 429 rate limiting
    yt_cookie_file = None
    if platform == Platform.YOUTUBE:
        cmd.extend(["--extractor-args", "youtube:player_client=web,default"])
        if settings.youtube_cookies:
            # Write cookie string to temp file
            yt_cookie_file = tempfile.NamedTemporaryFile(
                mode='w', suffix='.txt', prefix='yt_cookies_', delete=False, encoding='utf-8'
            )
            yt_cookie_file.write(settings.youtube_cookies)
            yt_cookie_file.close()
            cmd.extend(["--cookies", yt_cookie_file.name])
            logger.info(f"[Job {job_id}] Using YouTube cookies from settings")

    cmd.append(url)

    logger.info(f"[Job {job_id}] Running: {' '.join(cmd[:8])}...")

    process = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await process.communicate()

    # Cleanup temp cookie file
    if yt_cookie_file:
        try:
            os.unlink(yt_cookie_file.name)
        except Exception:
            pass

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

