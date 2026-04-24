"""
Configuration — Autonomous Content Bridge
Loads environment variables and provides app-wide settings.
"""
import os
from pathlib import Path
from pydantic_settings import BaseSettings
from functools import lru_cache


def _resolve_env_file() -> str:
    """Find a .env file that works on both Windows (dev) and Linux (VPS)."""
    override = os.environ.get("CONTENT_BRIDGE_ENV")
    if override:
        return override
    # Prefer repo-root .env for local dev
    repo_root = Path(__file__).resolve().parent.parent  # backend/config.py → content-bridge/
    local = repo_root / ".env"
    if local.exists():
        return str(local)
    # VPS default
    return "/opt/content-bridge/.env"


def _resolve_data_dir() -> str:
    """Data directory: VPS path on Linux, repo-local on Windows."""
    override = os.environ.get("CONTENT_BRIDGE_DATA")
    if override:
        return override
    vps = Path("/opt/content-bridge/data")
    if vps.exists() or vps.parent.exists():
        return str(vps)
    repo_root = Path(__file__).resolve().parent.parent
    local = repo_root / "data"
    local.mkdir(parents=True, exist_ok=True)
    return str(local)


class Settings(BaseSettings):
    """Application settings loaded from .env file."""

    # --- Kimi K2.5 (Moonshot AI) ---
    kimi_api_key: str = ""
    kimi_base_url: str = "https://api.moonshot.cn/v1"

    # --- Hermes Agent ---
    # Provider backing the Hermes Agent orchestrator:
    #   "openrouter"  → uses hermes_api_key + hermes_base_url (Hermes-3 on OpenRouter)
    #   "kimi"        → reuses kimi_api_key + kimi_base_url   (Moonshot Kimi models)
    #   "custom"      → uses hermes_api_key + hermes_base_url as-is
    hermes_provider: str = "openrouter"
    hermes_api_key: str = ""
    hermes_base_url: str = "https://openrouter.ai/api/v1"
    hermes_model: str = "nousresearch/hermes-3-llama-3.1-405b"

    # --- X / Twitter ---
    x_auth_token: str = ""
    x_ct0: str = ""

    # --- fal.ai (Image Generation) ---
    fal_api_key: str = ""

    # --- Douyin ---
    douyin_cookies: str = ""

    # --- YouTube ---
    youtube_cookies: str = ""  # Netscape cookie file content to bypass 429

    # --- App ---
    app_host: str = "0.0.0.0"
    app_port: int = 8000
    data_dir: str = _resolve_data_dir()
    log_level: str = "INFO"

    # --- Whisper ---
    whisper_model: str = "base"

    model_config = {
        "env_file": _resolve_env_file(),
        "env_file_encoding": "utf-8",
        "extra": "ignore",
    }

    @property
    def downloads_dir(self) -> Path:
        p = Path(self.data_dir) / "downloads"
        p.mkdir(parents=True, exist_ok=True)
        return p

    @property
    def processed_dir(self) -> Path:
        p = Path(self.data_dir) / "processed"
        p.mkdir(parents=True, exist_ok=True)
        return p

    @property
    def subtitles_dir(self) -> Path:
        p = Path(self.data_dir) / "subtitles"
        p.mkdir(parents=True, exist_ok=True)
        return p

    @property
    def logs_dir(self) -> Path:
        p = Path(self.data_dir) / "logs"
        p.mkdir(parents=True, exist_ok=True)
        return p

    @property
    def db_url(self) -> str:
        db_path = Path(self.data_dir) / "content_bridge.db"
        return f"sqlite+aiosqlite:///{db_path}"


@lru_cache
def get_settings() -> Settings:
    return Settings()


def get_job_settings(user_keys_json: str | None = None) -> Settings:
    """
    Create a Settings object with user-provided key overrides (BYOK mode).
    Falls back to .env values for any keys not provided by the user.
    """
    base = get_settings()
    if not user_keys_json:
        return base

    import json
    try:
        user_keys = json.loads(user_keys_json)
    except (json.JSONDecodeError, TypeError):
        return base

    if not user_keys:
        return base

    # Create a copy with overrides
    overrides = {}
    for field_name in [
        "kimi_api_key", "hermes_api_key", "fal_api_key",
        "hermes_provider", "hermes_model", "douyin_cookies", "youtube_cookies",
    ]:
        if field_name in user_keys and user_keys[field_name]:
            overrides[field_name] = user_keys[field_name]

    if not overrides:
        return base

    # Build new settings with overrides
    base_dict = {
        "kimi_api_key": base.kimi_api_key,
        "kimi_base_url": base.kimi_base_url,
        "hermes_provider": base.hermes_provider,
        "hermes_api_key": base.hermes_api_key,
        "hermes_base_url": base.hermes_base_url,
        "hermes_model": base.hermes_model,
        "fal_api_key": base.fal_api_key,
        "douyin_cookies": base.douyin_cookies,
        "youtube_cookies": base.youtube_cookies,
        "whisper_model": base.whisper_model,
        "data_dir": base.data_dir,
        "app_host": base.app_host,
        "app_port": base.app_port,
        "log_level": base.log_level,
    }
    base_dict.update(overrides)

    return Settings(**base_dict)
