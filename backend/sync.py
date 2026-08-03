"""Idempotent control-plane upload to the remote GPU service."""
from __future__ import annotations

import asyncio
import hashlib
import logging
import os
from typing import Optional

import aiohttp

from gpu_execution import require_remote_gpu

logger = logging.getLogger(__name__)
GPU_SERVICE_URL = os.environ.get("GPU_SERVICE_URL", "http://10.190.0.203:8877").rstrip("/")
_UPLOAD_LOCKS: dict[str, asyncio.Lock] = {}
_UPLOAD_CACHE: dict[tuple[int, str, int], str] = {}


def _file_fingerprint(path: str) -> tuple[str, int]:
    size = os.path.getsize(path)
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest(), size


def _lock_for(path: str) -> asyncio.Lock:
    return _UPLOAD_LOCKS.setdefault(os.path.abspath(path), asyncio.Lock())


async def sync_file(local_path: str, room_id: int) -> Optional[str]:
    """Upload one source artifact once, with a stable idempotency key.

    This function is transport-only. It never invokes ffmpeg/ffprobe and does
    not retry by reading the complete media file into memory.
    """
    record = require_remote_gpu("media upload")
    if not os.path.isfile(local_path):
        logger.error("Upload source is missing: %s", os.path.basename(local_path))
        return None
    fingerprint, size = _file_fingerprint(local_path)
    cache_key = (room_id, fingerprint, size)
    async with _lock_for(local_path):
        cached = _UPLOAD_CACHE.get(cache_key)
        if cached:
            return cached
        headers = {
            "X-Execution-Node": record.node,
            "X-Idempotency-Key": f"upload:{room_id}:{fingerprint}",
            "X-Artifact-Sha256": fingerprint,
        }
        url = f"{GPU_SERVICE_URL}/jobs"
        for attempt in range(1, 4):
            try:
                form = aiohttp.FormData()
                form.add_field("room_id", str(room_id))
                with open(local_path, "rb") as stream:
                    form.add_field("file", stream, filename=os.path.basename(local_path), content_type="video/mp4")
                    async with aiohttp.ClientSession() as session:
                        async with session.post(url, data=form, headers=headers, timeout=aiohttp.ClientTimeout(total=300)) as response:
                            body = await response.json() if response.status in (200, 201) else None
                            text = "" if body is not None else await response.text()
                if response.status == 201 and body and body.get("job_id"):
                    job_id = body["job_id"]
                    _UPLOAD_CACHE[cache_key] = job_id
                    logger.info("Uploaded artifact node=%s bytes=%d job_id=%s", record.node, size, job_id)
                    return job_id
                if response.status >= 500 and attempt < 3:
                    await asyncio.sleep(2 ** attempt)
                    continue
                logger.error("Upload rejected status=%s detail=%s", response.status, text[:200])
                return None
            except (OSError, aiohttp.ClientError, asyncio.TimeoutError) as exc:
                if attempt == 3:
                    logger.error("Upload failed after retries: %s", exc)
                    return None
                await asyncio.sleep(2 ** attempt)
    return None
