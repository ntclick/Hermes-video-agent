"""
Shelby Protocol — Decentralized Storage Service
Upload rendered videos to Shelby testnet for decentralized hot storage.
Adapted from PhoneZoo Gen music project's proven Shelby integration.

Two upload methods:
  1. Node.js SDK (primary) — full blockchain registration + chunked upload
  2. REST API (fallback)  — direct HTTP PUT/multipart, no Node.js needed
"""
import asyncio
import json
import logging
import os
import subprocess
import tempfile
import time
from pathlib import Path

from backend.config import get_settings

logger = logging.getLogger("content-bridge.shelby")


# ── Node.js Upload Script (embedded) ────────────────────────
# This .mjs script runs via `node` subprocess on the VPS.
# It uses the official @shelby-protocol/sdk for reliable upload.

_SHELBY_UPLOAD_MJS = r"""
import dns from 'dns'
dns.setDefaultResultOrder('ipv4first')

import fs from 'fs'

const filePath = process.argv[2]
const blobName = process.argv[3]
if (!filePath || !blobName) {
  process.stderr.write('Usage: shelby-upload.mjs <filePath> <blobName>\n')
  process.exit(1)
}

const rawKey = (process.env.SHELBY_PRIVATE_KEY || '').replace(/^ed25519-priv-/, '')
if (!rawKey) { process.stderr.write('SHELBY_PRIVATE_KEY not set\n'); process.exit(1) }

const fileBuffer = fs.readFileSync(filePath)

// Pre-resolve Shelby hostname via Cloudflare DoH
const shelbyHost = `api.${process.env.SHELBY_NETWORK || 'testnet'}.shelby.xyz`
let shelbyIP = null
try {
  const res = await fetch(
    `https://1.1.1.1/dns-query?name=${encodeURIComponent(shelbyHost)}&type=A`,
    { headers: { Accept: 'application/dns-json' } }
  )
  const data = await res.json()
  shelbyIP = data.Answer?.find(r => r.type === 1)?.data ?? null
  if (shelbyIP) process.stderr.write(`[dns] ${shelbyHost} → ${shelbyIP}\n`)
} catch (e) {
  process.stderr.write(`[dns] DoH failed: ${e.message}\n`)
}

// Patch dns.lookup for Shelby hostname only
if (shelbyIP) {
  const _nativeLookup = dns.lookup.bind(dns)
  const _ip = shelbyIP, _host = shelbyHost
  dns.lookup = (hostname, options, callback) => {
    if (hostname === _host) {
      const cb = typeof options === 'function' ? options : callback
      const opts = typeof options === 'object' && options !== null ? options : {}
      opts.all ? cb(null, [{ address: _ip, family: 4 }]) : cb(null, _ip, 4)
    } else if (typeof options === 'function') {
      _nativeLookup(hostname, options)
    } else {
      _nativeLookup(hostname, options, callback)
    }
  }
  process.stderr.write(`[dns] lookup patched for ${shelbyHost}\n`)
}

const { Ed25519PrivateKey, Account } = await import('@aptos-labs/ts-sdk')
const { ShelbyNodeClient } = await import('@shelby-protocol/sdk/node')

const privateKey = new Ed25519PrivateKey(rawKey)
const signer = Account.fromPrivateKey({ privateKey })
const client = new ShelbyNodeClient({
  network: process.env.SHELBY_NETWORK || 'testnet',
  apiKey: process.env.SHELBY_API_KEY,
})

const expirationDays = parseInt(process.env.SHELBY_EXPIRATION_DAYS || '30', 10)
const expirationMicros = BigInt(Date.now() + expirationDays * 24 * 60 * 60 * 1000) * 1000n

// Retry up to 3x with 5s delay
let lastErr
for (let attempt = 1; attempt <= 3; attempt++) {
  try {
    await client.upload({ signer, blobName, blobData: new Uint8Array(fileBuffer), expirationMicros })
    lastErr = null
    break
  } catch (e) {
    lastErr = e
    process.stderr.write(`[Shelby] Attempt ${attempt} failed: ${e.message}\n`)
    if (attempt < 3) await new Promise(r => setTimeout(r, 5000))
  }
}
if (lastErr) throw lastErr

const network = process.env.SHELBY_NETWORK || 'testnet'
const base = `https://api.${network}.shelby.xyz/shelby`
const encodedName = blobName.split('/').map(encodeURIComponent).join('/')
const url = `${base}/v1/blobs/${signer.accountAddress}/${encodedName}`
process.stdout.write(JSON.stringify({ url, sizeKb: Math.round(fileBuffer.length / 1024) }))
"""


def _get_shelby_env() -> dict:
    """Get Shelby-related environment variables."""
    settings = get_settings()
    return {
        "SHELBY_API_KEY": os.environ.get("SHELBY_API_KEY", ""),
        "SHELBY_ACCOUNT_ADDRESS": os.environ.get("SHELBY_ACCOUNT_ADDRESS", ""),
        "SHELBY_PRIVATE_KEY": os.environ.get("SHELBY_PRIVATE_KEY", ""),
        "SHELBY_NETWORK": os.environ.get("SHELBY_NETWORK", "testnet"),
        "SHELBY_EXPIRATION_DAYS": os.environ.get("SHELBY_EXPIRATION_DAYS", "30"),
    }


def _check_shelby_configured() -> bool:
    """Check if all required Shelby env vars are set."""
    env = _get_shelby_env()
    required = ["SHELBY_API_KEY", "SHELBY_ACCOUNT_ADDRESS", "SHELBY_PRIVATE_KEY"]
    missing = [k for k in required if not env.get(k)]
    if missing:
        logger.warning(f"Shelby not configured, missing: {', '.join(missing)}")
        return False
    return True


async def upload_to_shelby_via_node(file_path: str, blob_name: str, job_id: int) -> str:
    """
    Upload file to Shelby testnet via Node.js subprocess (primary method).
    Returns the public Shelby URL.
    """
    if not _check_shelby_configured():
        raise RuntimeError("Shelby credentials not configured in .env")

    # Ensure shelby-worker directory exists with SDK installed
    shelby_dir = Path("/opt/shelby-worker")
    if not shelby_dir.exists():
        # Try local path for Windows dev
        shelby_dir = Path(get_settings().data_dir) / "shelby-worker"
        shelby_dir.mkdir(parents=True, exist_ok=True)

    script_path = shelby_dir / "shelby-upload.mjs"
    package_json = shelby_dir / "package.json"

    # Write package.json if not exists
    if not package_json.exists():
        package_json.write_text('{"type":"module"}')
        # Install SDK
        logger.info(f"[Job {job_id}] Installing Shelby SDK...")
        proc = await asyncio.create_subprocess_exec(
            "npm", "install", "@shelby-protocol/sdk", "@aptos-labs/ts-sdk",
            cwd=str(shelby_dir),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        await proc.communicate()

    # Write upload script
    script_path.write_text(_SHELBY_UPLOAD_MJS)

    # Run the Node.js upload script
    env = {**os.environ, **_get_shelby_env()}
    logger.info(f"[Job {job_id}] Uploading to Shelby: {blob_name} ({Path(file_path).stat().st_size // 1024}KB)")

    proc = await asyncio.create_subprocess_exec(
        "node", "--dns-result-order=ipv4first", str(script_path), file_path, blob_name,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=env,
    )
    stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=300)  # 5 min timeout for video

    stderr_str = stderr.decode(errors="replace")
    if stderr_str:
        logger.info(f"[Job {job_id}] Shelby stderr: {stderr_str[:500]}")

    if proc.returncode != 0:
        raise RuntimeError(f"Shelby upload failed (exit {proc.returncode}): {stderr_str[:500]}")

    data = json.loads(stdout.decode())
    logger.info(f"[Job {job_id}] ✅ Shelby upload complete: {data['url']} ({data.get('sizeKb', '?')}KB)")
    return data["url"]


async def upload_to_shelby_rest(file_path: str, blob_name: str, job_id: int) -> str:
    """
    Fallback: Upload file to Shelby via REST API (no Node.js needed).
    Uses direct HTTP PUT for files, with multipart fallback for large files.
    """
    import httpx

    if not _check_shelby_configured():
        raise RuntimeError("Shelby credentials not configured in .env")

    env = _get_shelby_env()
    network = env["SHELBY_NETWORK"]
    account = env["SHELBY_ACCOUNT_ADDRESS"]
    api_key = env["SHELBY_API_KEY"]
    expiration_days = int(env["SHELBY_EXPIRATION_DAYS"])

    base_url = (
        "https://api.shelbynet.shelby.xyz/shelby"
        if network == "shelbynet"
        else f"https://api.{network}.shelby.xyz/shelby"
    )

    encoded_name = "/".join(part for part in blob_name.split("/"))

    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    file_bytes = Path(file_path).read_bytes()
    file_size_kb = len(file_bytes) // 1024

    # Try direct PUT first (works for files < 128MB)
    put_url = f"{base_url}/v1/blobs/{account}/{encoded_name}"
    put_headers = {**headers, "Content-Type": "video/mp4"}

    async with httpx.AsyncClient(timeout=120) as client:
        try:
            resp = await client.put(put_url, content=file_bytes, headers=put_headers)
            if resp.status_code in (200, 201, 204):
                logger.info(f"[Job {job_id}] ✅ Shelby REST PUT: {put_url} ({file_size_kb}KB)")
                return put_url
            else:
                logger.warning(f"[Job {job_id}] Shelby PUT returned {resp.status_code}: {resp.text[:200]}")
        except Exception as e:
            logger.warning(f"[Job {job_id}] Shelby PUT failed: {e}")

        # Fallback: multipart upload
        start_url = f"{base_url}/v1/blobs/{account}/{encoded_name}/multipart/start"
        expiration_micros = (int(time.time() * 1000) + expiration_days * 24 * 60 * 60 * 1000) * 1000
        start_body = json.dumps({"expirationMicros": expiration_micros})

        start_resp = await client.post(start_url, content=start_body, headers=headers)
        start_resp.raise_for_status()
        upload_id = start_resp.json().get("uploadId") or start_resp.json().get("upload_id", "")

        part_url = f"{base_url}/v1/blobs/{account}/{encoded_name}/multipart/{upload_id}/1"
        part_headers = {**headers, "Content-Type": "application/octet-stream"}
        part_resp = await client.put(part_url, content=file_bytes, headers=part_headers)
        part_resp.raise_for_status()
        etag = part_resp.headers.get("ETag", "")

        complete_url = f"{base_url}/v1/blobs/{account}/{encoded_name}/multipart/{upload_id}/complete"
        complete_body = json.dumps({"parts": [{"partNumber": 1, "etag": etag}]})
        complete_resp = await client.post(complete_url, content=complete_body, headers=headers)
        complete_resp.raise_for_status()

    public_url = f"{base_url}/v1/blobs/{account}/{encoded_name}"
    logger.info(f"[Job {job_id}] ✅ Shelby multipart upload: {public_url} ({file_size_kb}KB)")
    return public_url


async def upload_to_shelby(file_path: str, job_id: int, file_type: str = "video") -> str:
    """
    Main entry point: Upload a file to Shelby decentralized storage.
    Tries Node.js SDK first (with full blockchain registration), falls back to REST API.

    Args:
        file_path: Absolute path to the file to upload
        job_id: Job ID for naming
        file_type: "video" or "frames" — determines the blob path

    Returns:
        Public Shelby URL for the uploaded file
    """
    ext = Path(file_path).suffix or ".mp4"
    blob_name = f"hermes/content-bridge/{file_type}/{job_id}{ext}"

    # Try Node.js SDK first (most reliable, handles blockchain registration)
    try:
        return await upload_to_shelby_via_node(file_path, blob_name, job_id)
    except Exception as node_err:
        logger.warning(f"[Job {job_id}] Shelby Node.js upload failed, trying REST: {node_err}")

    # Fallback to REST API
    return await upload_to_shelby_rest(file_path, blob_name, job_id)
