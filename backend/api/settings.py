"""
Settings API — Autonomous Content Bridge
Endpoints to manage API keys and app configuration from the frontend.
"""
import logging
import os
import re
from pathlib import Path

from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from backend.database import get_db
from backend.models import XAccount

from backend.config import get_settings

logger = logging.getLogger("content-bridge.api.settings")

router = APIRouter(prefix="/api/settings", tags=["settings"])


def _resolve_env_path() -> Path:
    """Pick a writable .env location that works on both Windows (dev) and Linux (VPS)."""
    override = os.environ.get("CONTENT_BRIDGE_ENV")
    if override:
        return Path(override)
    # Prefer repo-root .env when running from the source tree (backend/api/settings.py)
    repo_root = Path(__file__).resolve().parents[2]
    local = repo_root / ".env"
    if local.exists():
        return local
    # VPS default
    vps = Path("/opt/content-bridge/.env")
    if vps.exists() or vps.parent.exists():
        return vps
    # Fall back to repo-root even if it doesn't exist yet (we'll create it)
    return local


ENV_PATH = _resolve_env_path()
logger.info(f"Using .env at: {ENV_PATH}")


class APIKeysUpdate(BaseModel):
    kimi_api_key: str | None = None
    hermes_api_key: str | None = None
    fal_api_key: str | None = None
    hermes_model: str | None = None
    hermes_provider: str | None = None
    x_cookies_json: str | None = None
    whisper_model: str | None = None
    douyin_cookies: str | None = None


class APIKeysResponse(BaseModel):
    """Returns masked keys — never expose full keys to frontend."""
    kimi_api_key: str
    kimi_configured: bool
    hermes_api_key: str
    hermes_configured: bool
    fal_api_key: str
    fal_configured: bool
    hermes_model: str
    hermes_provider: str
    hermes_ready: bool
    x_configured: bool
    whisper_model: str
    douyin_cookies: str
    douyin_configured: bool


def _mask_key(key: str) -> str:
    """Mask API key: show first 4 and last 4 chars only."""
    if not key or len(key) < 12:
        return "••••••••" if not key else key[:2] + "•" * (len(key) - 2)
    return key[:4] + "•" * (len(key) - 8) + key[-4:]


def _read_env() -> dict[str, str]:
    """Read .env file into a dict."""
    env = {}
    if ENV_PATH.exists():
        for line in ENV_PATH.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip()
    return env


def _write_env(env: dict[str, str]):
    """Write dict back to .env file, preserving comments."""
    # Make sure the target directory exists (fixes silent save failures on fresh Windows installs).
    ENV_PATH.parent.mkdir(parents=True, exist_ok=True)
    lines = []
    if ENV_PATH.exists():
        existing_lines = ENV_PATH.read_text(encoding="utf-8").splitlines()
        updated_keys = set()
        for line in existing_lines:
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                lines.append(line)
                continue
            if "=" in stripped:
                key = stripped.split("=", 1)[0].strip()
                if key in env:
                    lines.append(f"{key}={env[key]}")
                    updated_keys.add(key)
                else:
                    lines.append(line)
            else:
                lines.append(line)
        # Add any new keys not in original file
        for key, val in env.items():
            if key not in updated_keys:
                lines.append(f"{key}={val}")
    else:
        for key, val in env.items():
            lines.append(f"{key}={val}")

    ENV_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")


@router.get("", response_model=APIKeysResponse)
async def get_settings_api():
    """Get current settings with masked API keys."""
    env = _read_env()

    douyin_raw = env.get("DOUYIN_COOKIES", "")
    kimi_key = env.get("KIMI_API_KEY", "")
    hermes_key = env.get("HERMES_API_KEY", "")
    kimi_ok = bool(kimi_key) and "your_" not in kimi_key
    hermes_ok = bool(hermes_key) and "your_" not in hermes_key
    provider = env.get("HERMES_PROVIDER", "openrouter").lower()
    # Agent is "ready" if the key for the chosen provider is configured.
    hermes_ready = kimi_ok if provider == "kimi" else hermes_ok

    return APIKeysResponse(
        kimi_api_key=_mask_key(kimi_key),
        kimi_configured=kimi_ok,
        hermes_api_key=_mask_key(hermes_key),
        hermes_configured=hermes_ok,
        fal_api_key=_mask_key(env.get("FAL_API_KEY", "")),
        fal_configured=bool(env.get("FAL_API_KEY", "")) and "your_" not in env.get("FAL_API_KEY", ""),
        hermes_model=env.get("HERMES_MODEL", "nousresearch/hermes-3-llama-3.1-405b"),
        hermes_provider=provider,
        hermes_ready=hermes_ready,
        x_configured=True, # Deprecated for single account, now frontend uses XAccount API
        whisper_model=env.get("WHISPER_MODEL", "base"),
        # For multi-line cookie blobs, don't return the value to the frontend — just signal state.
        douyin_cookies="",
        douyin_configured=bool(douyin_raw),
    )

class XAccountCreate(BaseModel):
    cookies_json: str

@router.get("/x-accounts")
async def list_x_accounts(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(XAccount).order_by(XAccount.created_at.desc()))
    return [acc.to_dict() for acc in result.scalars().all()]

@router.post("/x-accounts/test-and-add")
async def test_and_add_x_account(body: XAccountCreate, db: AsyncSession = Depends(get_db)):
    import json
    import traceback
    import httpx

    try:
        cookies_list = json.loads(body.cookies_json)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid cookies JSON: {e}")

    # Build a cookie dict for httpx
    cookie_dict: dict[str, str] = {}
    for c in cookies_list:
        if "name" in c and "value" in c:
            cookie_dict[c["name"]] = c["value"]

    if not cookie_dict:
        raise HTTPException(status_code=400, detail="Parsed cookies JSON is empty.")

    # Quick sanity: check essential cookies
    essential = {"auth_token", "ct0"}
    missing = essential - set(cookie_dict.keys())
    if missing:
        raise HTTPException(
            status_code=400,
            detail=f"Missing essential cookies: {', '.join(missing)}. "
                   f"Make sure to export ALL cookies from x.com (need at least auth_token and ct0).",
        )

    ct0 = cookie_dict.get("ct0", "")
    logger.info(f"Testing X account with {len(cookie_dict)} cookies. Names: {sorted(cookie_dict.keys())}")

    name = "X Account"
    username = "unknown"

    # Twitter public bearer token (embedded in the web app, not a secret)
    BEARER = "AAAAAAAAAAAAAAAAAAAAANRILgAAAAAAnNwIzUejRCOuH5E6I8xnZz4puTs%3D1Zv7ttfk8LF81IUq16cHjhLTvJu4FA33AGWWjCpTnA"

    # Build raw cookie header string (bypasses httpx domain filtering)
    cookie_header = "; ".join(f"{k}={v}" for k, v in cookie_dict.items())

    try:
        headers = {
            "Cookie": cookie_header,
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                          "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.5",
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "none",
            "Upgrade-Insecure-Requests": "1"
        }

        async with httpx.AsyncClient(
            timeout=15,
            follow_redirects=False,  # We want to catch redirects to /login
        ) as client:
            logger.info("Fetching https://x.com/home to verify authentication...")
            resp = await client.get("https://x.com/home", headers=headers)
            logger.info(f"x.com/home status={resp.status_code}")

            # If not logged in, Twitter redirects to login page or returns an error status
            if resp.status_code in (301, 302, 307):
                loc = resp.headers.get("Location", "")
                if "login" in loc.lower() or "logout" in loc.lower() or "flow" in loc.lower():
                    raise HTTPException(
                        status_code=400,
                        detail="Authentication failed: cookies are expired or invalid (redirected to login).",
                    )
            elif resp.status_code >= 400:
                raise HTTPException(
                    status_code=400,
                    detail=f"Could not verify X credentials. Access denied (HTTP {resp.status_code}).",
                )

            # We received a 200 response (or similar), let's parse the HTML for user info
            html_content = resp.text
            
            # If the HTML contains a prominent login/signup block, it's likely a guest session
            if "signupButton" in html_content or "loginButton" in html_content:
                if '"is_logged_in":false' in html_content or 'isLoggedIn":false' in html_content:
                     raise HTTPException(
                        status_code=400,
                        detail="Authentication failed: session appears to be a guest session (isLoggedIn=false).",
                    )

            import re
            # Extract screen_name from embedded state
            screen_name_match = re.search(r'"screen_name":"([^"]+)"', html_content)
            if screen_name_match:
                username = screen_name_match.group(1)
            
            # Extract display name from embedded state
            name_match = re.search(r'"name":"([^"]+)"', html_content)
            if name_match:
                name = name_match.group(1)
            
            if username == "unknown":
                logger.warning("Could not extract username from x.com/home HTML. Cookies might still be valid.")
                # We'll accept it anyway, as long as it didn't redirect or show logged out
                
            logger.info(f"X auth success: @{username} ({name})")

    except HTTPException:
        raise
    except Exception as e:
        tb = traceback.format_exc()
        logger.error(f"X account test failed: {e}\n{tb}")
        detail = str(e) or repr(e) or "Unknown error (check server logs)"
        raise HTTPException(status_code=400, detail=f"Authentication test failed: {detail}")

    # Return details without saving to DB (BYOK mode - frontend will save to localStorage)
    import time
    return {
        "id": int(time.time()), # Generate a fake ID for frontend list rendering
        "name": name,
        "username": username,
        "cookies_json": body.cookies_json,
        "created_at": None
    }

@router.delete("/x-accounts/{account_id}")
async def delete_x_account(account_id: int, db: AsyncSession = Depends(get_db)):
    acc = await db.get(XAccount, account_id)
    if not acc:
        raise HTTPException(status_code=404, detail="Account not found")
    await db.delete(acc)
    await db.commit()
    return {"message": "Account deleted"}


@router.put("")
async def update_settings(body: APIKeysUpdate):
    """Update API keys in .env file."""
    env = _read_env()
    updated = []

    field_map = {
        "kimi_api_key": "KIMI_API_KEY",
        "hermes_api_key": "HERMES_API_KEY",
        "fal_api_key": "FAL_API_KEY",
        "hermes_model": "HERMES_MODEL",
        "hermes_provider": "HERMES_PROVIDER",
        "whisper_model": "WHISPER_MODEL",
        "douyin_cookies": "DOUYIN_COOKIES",
    }

    for field_name, env_key in field_map.items():
        value = getattr(body, field_name, None)
        if value is not None and value.strip():
            # Don't overwrite with masked values
            if "••••" in value:
                continue
            cleaned = value.strip()
            # Cookies can contain newlines/whitespace — keep them on a single .env line by
            # escaping newlines so the dotenv parser doesn't break.
            if env_key == "DOUYIN_COOKIES":
                try:
                    netscape_text, _ = _normalize_douyin_cookies(cleaned)
                    cleaned = netscape_text.replace("\r\n", "\n").replace("\n", "\\n")
                except ValueError as e:
                    raise HTTPException(status_code=400, detail=f"Invalid Douyin cookies format: {e}")
            env[env_key] = cleaned
            updated.append(env_key)

    # Handle cookies json
    if body.x_cookies_json:
        try:
            import json
            # Verify it's valid JSON
            json.loads(body.x_cookies_json)
            cookies_file = Path("/opt/content-bridge/data/x_cookies.json")
            cookies_file.parent.mkdir(parents=True, exist_ok=True)
            cookies_file.write_text(body.x_cookies_json, encoding="utf-8")
            updated.append("X_COOKIES")
        except json.JSONDecodeError:
            raise HTTPException(status_code=400, detail="Invalid JSON format for x_cookies_json")

    if updated:
        _write_env(env)
        logger.info(f"Settings updated: {', '.join(updated)}")

        # Clear cached settings so new values take effect
        from backend.config import get_settings as _gs
        _gs.cache_clear()

    return {
        "message": f"Updated {len(updated)} settings",
        "updated": updated,
        "restart_required": True,
    }


class TestConnectionRequest(BaseModel):
    api_key: str | None = None
    model: str | None = None


class DouyinCookiesBody(BaseModel):
    cookies: str


def _normalize_douyin_cookies(raw: str) -> tuple[str, dict]:
    """
    Accept either:
      - JSON array from EditThisCookie / Cookie-Editor
      - Netscape cookies.txt format
    Return (netscape_text, info) where info is {'count': N, 'names': [...]}.
    Raises ValueError if nothing usable is found.
    """
    import json as _json
    text = (raw or "").strip()
    if not text:
        raise ValueError("Empty cookies input")

    names: list[str] = []
    lines_out: list[str] = ["# Netscape HTTP Cookie File"]

    # Try JSON first
    parsed_json = None
    try:
        parsed_json = _json.loads(text)
    except Exception:
        parsed_json = None

    if isinstance(parsed_json, list) and parsed_json:
        for c in parsed_json:
            if not isinstance(c, dict) or "name" not in c or "value" not in c:
                continue
            domain = c.get("domain") or ".douyin.com"
            # Netscape requires leading dot for subdomain-matching
            include_subdomains = "TRUE" if domain.startswith(".") else "FALSE"
            path = c.get("path") or "/"
            secure = "TRUE" if c.get("secure") else "FALSE"
            expiry = c.get("expirationDate") or c.get("expiry") or 0
            try:
                expiry_int = int(expiry)
            except Exception:
                expiry_int = 0
            name = c["name"]
            value = c["value"]
            names.append(name)
            lines_out.append(f"{domain}\t{include_subdomains}\t{path}\t{secure}\t{expiry_int}\t{name}\t{value}")
        if not names:
            raise ValueError("JSON array parsed but contained no valid {name, value} entries")
        return "\n".join(lines_out) + "\n", {"count": len(names), "names": names, "format": "json→netscape"}

    # Otherwise treat as Netscape format directly
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        parts = stripped.split("\t")
        if len(parts) >= 7:
            names.append(parts[5])
    if not names:
        raise ValueError("Unrecognized cookies format (expected JSON array or Netscape cookies.txt)")
    return text if text.endswith("\n") else text + "\n", {"count": len(names), "names": names, "format": "netscape"}


@router.post("/save-douyin")
async def save_douyin_cookies(body: DouyinCookiesBody):
    """Parse + save Douyin cookies independently of the main settings form."""
    try:
        netscape_text, info = _normalize_douyin_cookies(body.cookies)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    # Store with newlines escaped so it fits on a single .env line.
    env = _read_env()
    env["DOUYIN_COOKIES"] = netscape_text.replace("\r\n", "\n").replace("\n", "\\n")
    _write_env(env)

    from backend.config import get_settings as _gs
    _gs.cache_clear()
    logger.info(f"Saved Douyin cookies: {info['count']} entries ({info['format']})")

    has_sessionid = any(n in ("sessionid", "sessionid_ss") for n in info["names"])
    return {
        "status": "ok",
        "message": f"Saved {info['count']} cookies ({info['format']}). "
                   + ("✅ sessionid present." if has_sessionid else "⚠️ Missing sessionid — download may fail."),
        "count": info["count"],
        "has_sessionid": has_sessionid,
    }


@router.post("/test-douyin")
async def test_douyin_cookies(body: DouyinCookiesBody | None = None):
    """
    Validate Douyin cookies via HTTP request (no Playwright needed).
    Calls Douyin's own API to verify login state.
    """
    import traceback

    # Pick source: inline input or stored .env value
    source = (body.cookies if body and body.cookies and body.cookies.strip() else None)
    if not source:
        env = _read_env()
        stored = env.get("DOUYIN_COOKIES", "")
        if not stored:
            return {"status": "error", "message": "No cookies to test — paste cookies or save first."}
        source = stored.replace("\\n", "\n")

    try:
        netscape_text, info = _normalize_douyin_cookies(source)
    except ValueError as e:
        return {"status": "error", "message": f"Parse failed: {e}"}

    # Build a cookies dict from Netscape text for httpx
    cookie_dict: dict[str, str] = {}
    for line in netscape_text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        parts = stripped.split("\t")
        if len(parts) >= 7:
            name, value = parts[5], parts[6]
            cookie_dict[name] = value

    if not cookie_dict:
        return {"status": "error", "message": "Parsed 0 usable cookies."}

    # Quick sanity check for critical cookie names
    has_sessionid = any(n in cookie_dict for n in ("sessionid", "sessionid_ss"))

    logger.info(f"Testing Douyin cookies: {info['count']} entries ({info['format']}). "
                f"sessionid={'present' if has_sessionid else 'MISSING'}")

    # --- HTTP-based login check ---
    try:
        import httpx

        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                          "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Referer": "https://www.douyin.com/",
            "Accept": "application/json, text/plain, */*",
        }

        async with httpx.AsyncClient(
            timeout=15,
            headers=headers,
            cookies=cookie_dict,
            follow_redirects=True,
        ) as client:
            # Primary: Try user info API
            try:
                resp = await client.get("https://www.douyin.com/passport/web/account/info/")
                logger.info(f"Douyin account/info status={resp.status_code}")

                if resp.status_code == 200:
                    data = resp.json()
                    # data usually has {"data": {"username": "...", ...}, "message": "success"}
                    user_data = data.get("data", {})
                    username = user_data.get("username") or user_data.get("screen_name") or ""
                    uid = user_data.get("uid") or user_data.get("user_id") or ""
                    err_code = data.get("status_code") or data.get("err_code", 0)

                    if username or uid:
                        label = f"@{username}" if username else f"UID:{uid}"
                        return {
                            "status": "ok",
                            "message": f"✅ Logged in as {label}. {info['count']} cookies ({info['format']}).",
                        }
                    elif err_code and err_code != 0:
                        return {
                            "status": "error",
                            "message": f"Douyin API returned error code {err_code}. Cookies may be expired.",
                        }
            except Exception as e:
                logger.warning(f"Douyin account/info check failed: {e}")

            # Fallback: Try fetching home page and checking for login indicators
            try:
                resp = await client.get("https://www.douyin.com/", headers={
                    **headers,
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                })
                body_text = resp.text[:5000]  # Check first 5KB
                current_url = str(resp.url)

                if "passport" in current_url.lower() or "login" in current_url.lower():
                    return {"status": "error", "message": "Redirected to login — cookies expired/invalid."}

                # If we can see user-related content in the response, we're likely logged in or at least not strictly blocked
                if has_sessionid:
                    return {
                        "status": "ok",
                        "message": f"✅ Parsed {info['count']} cookies, sessionid present. "
                                   f"API blocked check but downloads should work via yt-dlp.",
                    }
                else:
                    return {
                        "status": "warn",
                        "message": f"⚠️ Parsed {info['count']} cookies but sessionid is MISSING. "
                                   f"Downloads will likely fail. Re-export cookies after logging in.",
                    }
            except Exception as e2:
                logger.warning(f"Douyin homepage fallback check failed: {e2}")

            # Last resort
            if has_sessionid:
                return {
                    "status": "ok",
                    "message": f"✅ Parsed {info['count']} cookies ({info['format']}), sessionid present. "
                               f"API test skipped — downloads should work.",
                }
            return {
                "status": "error",
                "message": f"Parsed {info['count']} cookies but sessionid missing and could not verify login.",
            }

    except ImportError:
        # httpx not available — just return parse result
        return {
            "status": "ok" if has_sessionid else "warn",
            "message": f"{'✅' if has_sessionid else '⚠️'} Parsed OK: {info['count']} cookies ({info['format']}). "
                       f"{'sessionid present.' if has_sessionid else 'sessionid MISSING.'} ",
        }
    except Exception as e:
        tb = traceback.format_exc()
        logger.error(f"Douyin cookie test failed: {e}\n{tb}")
        return {"status": "error", "message": f"Browser check failed: {str(e) or repr(e)}"}

@router.post("/test-kimi")
async def test_kimi_connection(body: TestConnectionRequest | None = None):
    """Test Kimi API connection."""
    env = _read_env()
    
    # Use provided key (if not masked) or fallback to env
    api_key = ""
    if body and body.api_key and "••••" not in body.api_key:
        api_key = body.api_key
    else:
        api_key = env.get("KIMI_API_KEY", "")

    if not api_key or "your_" in api_key:
        return {"status": "error", "message": "Kimi API key not configured. Please enter a key or save settings first."}

    try:
        from openai import AsyncOpenAI
        
        # Determine base url try list
        current_base = env.get("KIMI_BASE_URL", "https://api.moonshot.ai/v1")
        bases_to_try = [current_base]
        if current_base == "https://api.moonshot.cn/v1":
            bases_to_try.append("https://api.moonshot.ai/v1")
        elif current_base == "https://api.moonshot.ai/v1":
            bases_to_try.append("https://api.moonshot.cn/v1")
            
        last_error = None
        for base_url in bases_to_try:
            try:
                client = AsyncOpenAI(api_key=api_key, base_url=base_url, max_retries=1)
                response = await client.chat.completions.create(
                    model="kimi-k2.6", # use valid model
                    messages=[{"role": "user", "content": "ping"}],
                    extra_body={"thinking": {"type": "disabled"}},
                    max_tokens=5,
                    timeout=5.0
                )
                
                # If we succeeded on a different base_url, save it
                if base_url != env.get("KIMI_BASE_URL"):
                    env["KIMI_BASE_URL"] = base_url
                    _write_env(env)
                    
                return {"status": "ok", "message": f"Connected! Response: {response.choices[0].message.content} (Endpoint: {base_url})"}
            except Exception as e:
                last_error = str(e)
                if "Authentication" in last_error or "401" in last_error:
                    continue # Try next base URL
                else:
                    break # If it's a network error or something else, abort
                    
        return {"status": "error", "message": last_error}
    except Exception as e:
        return {"status": "error", "message": str(e)}


class HermesTestRequest(TestConnectionRequest):
    provider: str | None = None

@router.post("/test-hermes")
async def test_hermes_connection(body: HermesTestRequest | None = None):
    """Test Hermes Agent connection against the selected provider."""
    env = _read_env()

    provider = ((body.provider if body else None) or env.get("HERMES_PROVIDER", "openrouter")).lower()

    # Pick the right key + base_url based on provider.
    # Always prefer body.api_key over env so the user can test before saving.
    body_key = (body.api_key or "") if body else ""
    body_key_clean = body_key if "••••" not in body_key else ""

    if provider == "kimi":
        api_key = body_key_clean or env.get("KIMI_API_KEY", "")
        base_url = env.get("KIMI_BASE_URL", "https://api.moonshot.ai/v1")
        default_model = "kimi-k2.6"
        key_label = "Kimi"
    else:
        api_key = body_key_clean or env.get("HERMES_API_KEY", "")
        base_url = env.get("HERMES_BASE_URL", "https://openrouter.ai/api/v1")
        default_model = "nousresearch/hermes-4-405b"
        key_label = "Hermes"

    model = (body.model if body and body.model else env.get("HERMES_MODEL", default_model))

    if not api_key or "your_" in api_key:
        return {"status": "error", "message": f"{key_label} API key not configured for provider '{provider}'."}

    try:
        from openai import AsyncOpenAI
        client = AsyncOpenAI(api_key=api_key, base_url=base_url)
        response = await client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": "Say 'OK' in one word."}],
            max_tokens=5,
        )
        return {
            "status": "ok",
            "message": f"Connected via {provider} ({model}). Response: {response.choices[0].message.content}",
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}
